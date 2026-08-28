"""Shadowverse: Worlds Beyond 官方卡组二维码解析。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np


CUSTOM_DICT = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
OFFICIAL_HOSTS = {"shadowverse-wb.com", "www.shadowverse-wb.com"}
EXPECTED_DECK_SIZE = 40


class DeckQrError(ValueError):
    """二维码或官方卡组 hash 无法安全解析。"""


@dataclass(frozen=True)
class ParsedOfficialDeck:
    format_version: int
    class_id: int
    card_ids: Tuple[str, ...]
    source: str = ""

    @property
    def records(self) -> Tuple[Dict[str, Any], ...]:
        counts = Counter(self.card_ids)
        seen = set()
        records = []
        for card_id in self.card_ids:
            if card_id in seen:
                continue
            seen.add(card_id)
            records.append({"card_id": card_id, "count": counts[card_id]})
        return tuple(records)


def decode_shortcode(shortcode: str) -> int:
    token = str(shortcode or "").strip()
    if len(token) != 4 or any(ch not in CUSTOM_DICT for ch in token):
        return 0
    return (
        CUSTOM_DICT.index(token[0]) << 18
        | CUSTOM_DICT.index(token[1]) << 12
        | CUSTOM_DICT.index(token[2]) << 6
        | CUSTOM_DICT.index(token[3])
    )


def _extract_hash(text: str) -> tuple[str, str]:
    raw = str(text or "").strip()
    if not raw:
        raise DeckQrError("二维码内容为空")

    if "://" in raw:
        parsed = urlsplit(raw)
        host = str(parsed.hostname or "").casefold()
        if host not in OFFICIAL_HOSTS:
            raise DeckQrError("只允许导入 shadowverse-wb.com 官方卡组链接")
        normalized_path = parsed.path.rstrip("/").casefold()
        if not normalized_path.endswith("/deck/detail"):
            raise DeckQrError("二维码不是官方卡组详情链接")
        values = parse_qs(parsed.query, keep_blank_values=False).get("hash", [])
        if not values:
            raise DeckQrError("官方卡组链接缺少 hash 参数")
        return str(values[0]).strip(), raw

    if raw.startswith("hash="):
        raw = raw[5:].strip()
    return raw, raw


def parse_official_deck_payload(
    text: str,
    *,
    require_full_deck: bool = True,
) -> ParsedOfficialDeck:
    deck_hash, source = _extract_hash(text)
    parts = deck_hash.split(".")
    if len(parts) < 3:
        raise DeckQrError("官方卡组 hash 格式不完整")
    try:
        format_version = int(parts[0])
        class_id = int(parts[1])
    except (TypeError, ValueError) as exc:
        raise DeckQrError("官方卡组 hash 头部无效") from exc
    if format_version <= 0 or not 0 <= class_id <= 7:
        raise DeckQrError("官方卡组 hash 版本或职业编号无效")

    card_ids = []
    for token in parts[2:]:
        card_id = decode_shortcode(token)
        if card_id <= 0:
            raise DeckQrError(f"卡牌短码无效: {token}")
        card_ids.append(str(card_id))

    if require_full_deck and len(card_ids) != EXPECTED_DECK_SIZE:
        raise DeckQrError(
            f"官方构筑应为 {EXPECTED_DECK_SIZE} 张，二维码实际包含 {len(card_ids)} 张"
        )
    if len(card_ids) > EXPECTED_DECK_SIZE:
        raise DeckQrError(f"二维码卡牌数量超过 {EXPECTED_DECK_SIZE} 张")
    counts = Counter(card_ids)
    over_limit = [card_id for card_id, count in counts.items() if count > 3]
    if over_limit:
        raise DeckQrError("二维码存在超过三张上限的卡牌: " + ", ".join(over_limit[:5]))

    return ParsedOfficialDeck(
        format_version=format_version,
        class_id=class_id,
        card_ids=tuple(card_ids),
        source=source,
    )


def decode_qr_bgr(image: np.ndarray) -> str:
    if image is None or not isinstance(image, np.ndarray) or image.size <= 0:
        raise DeckQrError("二维码图片为空")
    detector = cv2.QRCodeDetector()
    value, points, _straight = detector.detectAndDecode(image)
    if not value or points is None:
        raise DeckQrError("未在图片中识别到二维码")
    return str(value).strip()


def decode_qr_path(path: str) -> str:
    filename = str(path or "").strip()
    if not filename:
        raise DeckQrError("未选择二维码图片")
    try:
        encoded = np.fromfile(filename, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    except Exception as exc:
        raise DeckQrError(f"二维码图片读取失败: {exc}") from exc
    return decode_qr_bgr(image)


def qimage_to_bgr(image: Any) -> np.ndarray:
    """把 QImage 转成独立的 BGR ndarray，避免悬挂 Qt 内存。"""

    try:
        from PyQt5.QtGui import QImage

        converted = image.convertToFormat(QImage.Format_RGB888)
        width = int(converted.width())
        height = int(converted.height())
        stride = int(converted.bytesPerLine())
        pointer = converted.bits()
        pointer.setsize(height * stride)
        raw = np.frombuffer(pointer, dtype=np.uint8).reshape((height, stride))
        rgb = raw[:, : width * 3].reshape((height, width, 3)).copy()
    except Exception as exc:
        raise DeckQrError(f"剪贴板图片读取失败: {exc}") from exc
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
