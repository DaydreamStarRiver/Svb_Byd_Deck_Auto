"""Selectable OCR runtime used by battle-state and page recognition.

The legacy path keeps the existing EasyOCR -> MNIST fallback.  The Maa path
uses MaaFramework with MaaCommonAssets models and deliberately keeps the
framework behind a lazy import, so selecting the legacy backend does not load
the Maa native libraries.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

import cv2
import numpy as np

from src.config.settings import EXPERIMENTAL_MAA_RECOGNITION_ENABLED
from src.utils.hp_detection import predict_digit_easyocr, predict_digit_mnist
from src.utils.resource_utils import resource_path
from src.app.native_runtime import loaded_cpp_runtime_paths, prepare_windows_cpp_runtime


logger = logging.getLogger(__name__)

BACKEND_LEGACY = "legacy"
BACKEND_MAA = "maa"


@dataclass(frozen=True)
class OCRItem:
    text: str
    score: float
    box: tuple[int, int, int, int]


def normalize_backend(value: object) -> str:
    if not EXPERIMENTAL_MAA_RECOGNITION_ENABLED:
        return BACKEND_LEGACY
    text = str(value or "").strip().lower()
    return BACKEND_MAA if text in {"maa", "maafw", "maaframework"} else BACKEND_LEGACY


def _to_bgr(image: Any) -> np.ndarray:
    if isinstance(image, np.ndarray):
        array = image
    else:
        array = np.asarray(image)

    if array.ndim == 2:
        return cv2.cvtColor(array.astype(np.uint8, copy=False), cv2.COLOR_GRAY2BGR)
    if array.ndim != 3:
        raise ValueError(f"unsupported OCR image shape: {array.shape}")
    if array.shape[2] == 4:
        return cv2.cvtColor(array.astype(np.uint8, copy=False), cv2.COLOR_BGRA2BGR)
    if array.shape[2] != 3:
        raise ValueError(f"unsupported OCR channel count: {array.shape[2]}")
    return array.astype(np.uint8, copy=False)


def _clip_roi(
    image: np.ndarray,
    roi: Optional[Sequence[int]],
) -> tuple[np.ndarray, int, int]:
    if not roi or len(roi) < 4:
        return image, 0, 0
    height, width = image.shape[:2]
    x1, y1, x2, y2 = [int(value) for value in roi[:4]]
    x1 = max(0, min(width, x1))
    x2 = max(0, min(width, x2))
    y1 = max(0, min(height, y1))
    y2 = max(0, min(height, y2))
    if x2 <= x1 or y2 <= y1:
        return image[0:0, 0:0], x1, y1
    return image[y1:y2, x1:x2], x1, y1


class _MaaEngine:
    """One Maa resource/tasker pair bound to one OCR model directory."""

    def __init__(self, model_dir: str):
        prepare_windows_cpp_runtime()
        from maa.library import Library
        from maa.resource import Resource
        from maa.tasker import Tasker

        # Load before constructing Resource so a failed DLL import does not
        # leave Maa's Resource.__del__ with a half-initialized native handle.
        try:
            Library.framework()
        except OSError as exc:
            raise RuntimeError(
                f"Maa native DLL load failed: {Library.framework_libpath}: {exc}"
            ) from exc

        self._lock = threading.RLock()
        self._resource = Resource()
        load_job = self._resource.post_ocr_model(model_dir).wait()
        if not load_job.succeeded:
            raise RuntimeError(f"Maa OCR model load failed: {model_dir}")

        self._tasker = Tasker()
        # Direct recognition does not need a device controller.  Maa's public
        # Tasker.bind currently requires both resource and controller, so bind
        # only the resource through the same official C API used by Tasker.
        self._tasker._resource_holder = self._resource
        bound = bool(
            Library.framework().MaaTaskerBindResource(
                self._tasker._handle,
                self._resource._handle,
            )
        )
        if not bound or not self._tasker.inited:
            raise RuntimeError(f"Maa OCR tasker bind failed: {model_dir}")

    def recognize(
        self,
        image: np.ndarray,
        *,
        only_rec: bool,
        threshold: float,
    ) -> list[OCRItem]:
        from maa.pipeline import JOCR, JRecognitionType

        if image.size == 0:
            return []
        with self._lock:
            detail = self._tasker.post_recognition(
                JRecognitionType.OCR,
                JOCR(
                    expected=[],
                    threshold=max(0.05, min(1.0, float(threshold))),
                    only_rec=bool(only_rec),
                    order_by="Horizontal",
                ),
                image,
            ).wait().get()

            results: list[OCRItem] = []
            for node in detail.nodes:
                recognition = node.recognition
                if recognition is None:
                    continue
                for item in recognition.all_results:
                    text = str(getattr(item, "text", "") or "").strip()
                    score = float(getattr(item, "score", 0.0) or 0.0)
                    box_value = getattr(item, "box", None)
                    if box_value is None:
                        box = (0, 0, image.shape[1], image.shape[0])
                    else:
                        box = tuple(int(value) for value in box_value)
                    results.append(OCRItem(text=text, score=score, box=box))
            return results


_MAA_ENGINES: dict[str, _MaaEngine] = {}
_MAA_ENGINES_LOCK = threading.Lock()


def _get_maa_engine(model_dir: str) -> _MaaEngine:
    key = os.path.normcase(os.path.abspath(model_dir))
    with _MAA_ENGINES_LOCK:
        engine = _MAA_ENGINES.get(key)
        if engine is None:
            engine = _MaaEngine(model_dir)
            _MAA_ENGINES[key] = engine
        return engine


_DIGIT_SUBSTITUTIONS = str.maketrans(
    {
        "O": "0",
        "o": "0",
        "I": "1",
        "i": "1",
        "l": "1",
        "|": "1",
        "Z": "2",
        "z": "2",
        "S": "5",
        "s": "5",
        "B": "8",
    }
)


def _numeric_text(value: object, *, keep_slash: bool = False) -> str:
    text = str(value or "").translate(_DIGIT_SUBSTITUTIONS)
    pattern = r"[^0-9/+]+" if keep_slash else r"[^0-9]+"
    return re.sub(pattern, "", text)


def _normalized_page_text(value: object) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", str(value or "").casefold())


class RecognitionService:
    """Backend-neutral OCR facade with Maa/legacy selection and fallbacks."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        legacy_reader: Any = None,
    ):
        recognition = config.get("recognition", {}) if isinstance(config, dict) else {}
        if not isinstance(recognition, dict):
            recognition = {}
        self.requested_backend = normalize_backend(recognition.get("backend", BACKEND_LEGACY))
        self.active_backend = self.requested_backend
        self.page_text_fallback_enabled = bool(
            recognition.get("page_text_fallback", True)
        )
        self.threshold = max(
            0.05,
            min(1.0, float(recognition.get("maa_threshold", 0.3) or 0.3)),
        )
        self.legacy_reader = legacy_reader
        self._digit_engine: Optional[_MaaEngine] = None
        self._page_engine: Optional[_MaaEngine] = None
        self._page_cache_source: Optional[np.ndarray] = None
        self._page_cache: list[OCRItem] = []
        self._page_cache_lock = threading.RLock()

        if self.requested_backend == BACKEND_MAA:
            model_root = str(recognition.get("maa_model_dir", "models/maa_ocr") or "models/maa_ocr")
            model_root = resource_path(model_root)
            try:
                self._digit_engine = _get_maa_engine(os.path.join(model_root, "en_us"))
                self._page_engine = _get_maa_engine(os.path.join(model_root, "zh_cn"))
                logger.info("MaaFramework OCR initialized: %s", model_root)
            except Exception as exc:
                logger.exception(
                    "MaaFramework OCR initialization failed; falling back to legacy: %s; "
                    "Python=%s; C++ runtime=%s. 若先加载了 PyQt 旧运行库，请完全退出软件后重启。",
                    exc,
                    sys.executable,
                    loaded_cpp_runtime_paths(),
                )
                self.active_backend = BACKEND_LEGACY
                self._ensure_legacy_reader()

    @property
    def uses_maa(self) -> bool:
        return self.active_backend == BACKEND_MAA and self._digit_engine is not None

    def _ensure_legacy_reader(self) -> Any:
        if self.legacy_reader is None:
            try:
                from src.utils.gpu_utils import get_easyocr_reader

                self.legacy_reader = get_easyocr_reader()
            except Exception as exc:
                logger.warning("Legacy EasyOCR reader unavailable: %s", exc)
        return self.legacy_reader

    def read_texts(
        self,
        image: Any,
        *,
        roi: Optional[Sequence[int]] = None,
        only_rec: bool = False,
        digits: bool = False,
        threshold: Optional[float] = None,
    ) -> list[OCRItem]:
        bgr = _to_bgr(image)
        crop, offset_x, offset_y = _clip_roi(bgr, roi)
        if crop.size == 0:
            return []
        used_threshold = self.threshold if threshold is None else float(threshold)

        if self.uses_maa:
            engine = self._digit_engine if digits else self._page_engine
            if engine is None:
                return []
            local_items = engine.recognize(
                crop,
                only_rec=only_rec,
                threshold=used_threshold,
            )
        else:
            reader = self._ensure_legacy_reader()
            if reader is None:
                return []
            allowlist = "0123456789/+" if digits else None
            try:
                raw = reader.readtext(
                    crop,
                    allowlist=allowlist,
                    detail=1,
                    paragraph=False,
                )
            except Exception as exc:
                logger.debug("EasyOCR read failed: %s", exc)
                return []
            local_items = []
            for entry in raw or []:
                try:
                    points, text, score = entry
                    xs = [int(round(point[0])) for point in points]
                    ys = [int(round(point[1])) for point in points]
                    box = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
                    local_items.append(OCRItem(str(text), float(score), box))
                except Exception:
                    continue

        return [
            OCRItem(
                item.text,
                item.score,
                (item.box[0] + offset_x, item.box[1] + offset_y, item.box[2], item.box[3]),
            )
            for item in local_items
        ]

    def recognize_digit_sequence(
        self,
        digit_images: Iterable[np.ndarray],
        mnist_model: Any,
    ) -> str:
        values: list[str] = []
        reader = None if self.uses_maa else self._ensure_legacy_reader()
        for digit_image in digit_images:
            prediction = ""
            if self.uses_maa:
                try:
                    image = np.asarray(digit_image, dtype=np.uint8)
                    image = cv2.resize(image, (84, 84), interpolation=cv2.INTER_CUBIC)
                    items = self.read_texts(
                        image,
                        only_rec=True,
                        digits=True,
                        threshold=0.1,
                    )
                    candidates = [
                        (_numeric_text(item.text), item.score)
                        for item in items
                        if len(_numeric_text(item.text)) == 1
                    ]
                    if candidates:
                        prediction = max(candidates, key=lambda item: item[1])[0]
                except Exception as exc:
                    logger.debug("Maa digit recognition failed: %s", exc)
            else:
                prediction = predict_digit_easyocr(reader, digit_image)
                if prediction == "error":
                    prediction = ""

            if not prediction:
                fallback = predict_digit_mnist(mnist_model, digit_image)
                prediction = str(fallback) if fallback >= 0 else "?"
            values.append(prediction)
        return "".join(values)

    def read_integer(
        self,
        image: Any,
        roi: Sequence[int],
        *,
        maximum: int = 99,
    ) -> Optional[int]:
        items = self.read_texts(
            image,
            roi=roi,
            only_rec=True,
            digits=True,
            threshold=0.1,
        )
        candidates: list[tuple[int, float]] = []
        for item in items:
            text = _numeric_text(item.text)
            if not text:
                continue
            try:
                value = int(text)
            except ValueError:
                continue
            if 0 <= value <= maximum:
                candidates.append((value, item.score))
        return max(candidates, key=lambda item: item[1])[0] if candidates else None

    def read_ratio(
        self,
        image: Any,
        roi: Sequence[int],
    ) -> tuple[Optional[int], Optional[int], bool]:
        items = self.read_texts(
            image,
            roi=roi,
            only_rec=False,
            digits=True,
            threshold=0.1,
        )
        active_bonus = False
        for item in sorted(items, key=lambda value: (-value.score, value.box[0])):
            text = _numeric_text(item.text, keep_slash=True)
            match = re.search(r"(\d{1,2})(\+\d{1,2})?/(\d{1,2})", text)
            if not match:
                continue
            current = int(match.group(1))
            maximum = int(match.group(3))
            active_bonus = bool(match.group(2))
            if current <= 20 and maximum <= 20:
                return current, maximum, active_bonus

        # Detection can split current and maximum into separate boxes.  Keep a
        # conservative left-to-right fallback for that case.
        numbers: list[int] = []
        for item in sorted(items, key=lambda value: value.box[0]):
            text = _numeric_text(item.text)
            if text and len(text) <= 2:
                value = int(text)
                if 0 <= value <= 20:
                    numbers.append(value)
        if len(numbers) >= 2:
            return numbers[0], numbers[1], active_bonus
        return None, None, active_bonus

    def _page_items(self, image: np.ndarray) -> list[OCRItem]:
        with self._page_cache_lock:
            if self._page_cache_source is image:
                return list(self._page_cache)
            items = self.read_texts(
                image,
                only_rec=False,
                digits=False,
                threshold=0.1,
            )
            self._page_cache_source = image
            self._page_cache = list(items)
            return items

    def match_page_aliases(
        self,
        image: np.ndarray,
        aliases: Iterable[str],
    ) -> Optional[OCRItem]:
        if not self.uses_maa or not self.page_text_fallback_enabled:
            return None
        normalized_aliases = [
            _normalized_page_text(alias) for alias in aliases if _normalized_page_text(alias)
        ]
        if not normalized_aliases:
            return None

        matches: list[OCRItem] = []
        for item in self._page_items(image):
            item_text = _normalized_page_text(item.text)
            if not item_text:
                continue
            # Alias may be a stable prefix contained in a noisier OCR result
            # (for example "随机" in "随机封戟").  Do not accept the reverse:
            # one-character OCR fragments such as "定" or "回合" otherwise
            # cause unrelated pages to match decision/end-turn buttons.
            if any(alias in item_text for alias in normalized_aliases):
                matches.append(item)
        return max(matches, key=lambda item: item.score) if matches else None
