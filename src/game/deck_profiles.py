"""Prepare saved deck snapshots for per-device runtime use.

The manual deck workspace owns the persistent ``card_cost`` directory.  Automatic
rotation must not rewrite that shared directory while device threads are running,
so each mapped deck is materialized into a private temporary directory and its
hand-card recognizer is built before the game UI is clicked.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.config.paths import get_app_root
from src.game.sift_card_recognition import SiftCardRecognition
from src.ui.card_catalog import get_card_resource_root
from src.ui.deck_io import (
    build_card_source_index,
    build_card_variant_index,
    extract_deck_strategy_config,
    normalize_deck_card_records,
    normalize_derived_card_records,
    resolve_runtime_card_paths,
)
from src.utils.card_filename import parse_card_filename


class DeckProfileError(RuntimeError):
    """A saved deck cannot safely become a runtime deck."""


@dataclass
class RuntimeDeckProfile:
    filename: str
    name: str
    strategy_config: Dict[str, Any]
    template_dir: str
    recognizer: SiftCardRecognition
    card_count: int
    distinct_count: int
    derived_count: int
    costs: Dict[int, int]
    _temporary_dir: tempfile.TemporaryDirectory[str]

    def dashboard_summary(self, *, slot: Optional[int] = None) -> Dict[str, Any]:
        return {
            "name": self.name,
            "file": self.filename,
            "slot": int(slot) if slot is not None else None,
            "count": self.card_count,
            "distinct_count": self.distinct_count,
            "derived_count": self.derived_count,
            "costs": dict(self.costs),
            "applied": True,
        }

    def close(self) -> None:
        try:
            self._temporary_dir.cleanup()
        except Exception:
            pass


class RuntimeDeckProfileLoader:
    """Resolve, validate and cache saved decks for one device runtime."""

    def __init__(self, *, app_root: Optional[str] = None):
        self.app_root = os.path.abspath(app_root or get_app_root())
        self.decks_dir = os.path.join(self.app_root, "saved_decks")
        self.resource_root = get_card_resource_root(self.app_root)
        self._exact_index: Optional[Dict[str, str]] = None
        self._stem_index: Optional[Dict[str, str]] = None
        self._variant_index = None
        self._cache: Dict[str, RuntimeDeckProfile] = {}

    def _ensure_indexes(self) -> None:
        if self._exact_index is None or self._stem_index is None:
            self._exact_index, self._stem_index = build_card_source_index(
                self.resource_root
            )
        if self._variant_index is None:
            self._variant_index = build_card_variant_index(self.resource_root)

    def _deck_path(self, filename: str) -> tuple[str, str]:
        raw = str(filename or "").strip()
        safe_name = os.path.basename(raw)
        if not raw or safe_name != raw or not safe_name.casefold().endswith(".json"):
            raise DeckProfileError("本地构筑文件名无效")
        path = os.path.abspath(os.path.join(self.decks_dir, safe_name))
        try:
            common = os.path.commonpath((self.decks_dir, path))
        except ValueError as exc:
            raise DeckProfileError("本地构筑路径无效") from exc
        if os.path.normcase(common) != os.path.normcase(self.decks_dir):
            raise DeckProfileError("本地构筑路径超出 saved_decks")
        if not os.path.isfile(path):
            raise DeckProfileError(f"本地构筑不存在: {safe_name}")
        return safe_name, path

    def load(self, filename: str) -> RuntimeDeckProfile:
        safe_name, path = self._deck_path(filename)
        cache_key = safe_name.casefold()
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            with open(path, "r", encoding="utf-8-sig") as stream:
                data = json.load(stream)
        except Exception as exc:
            raise DeckProfileError(f"本地构筑读取失败: {safe_name}: {exc}") from exc
        if not isinstance(data, dict):
            raise DeckProfileError(f"本地构筑格式错误: {safe_name}")

        cards = normalize_deck_card_records(data.get("cards") or [])
        derived_cards = normalize_derived_card_records(data.get("derived_cards") or [])
        if not cards:
            raise DeckProfileError(f"本地构筑没有主卡: {safe_name}")

        self._ensure_indexes()
        assert self._exact_index is not None
        assert self._stem_index is not None

        source_by_destination: Dict[str, str] = {}
        missing: list[str] = []
        costs: Counter[int] = Counter()

        def collect(reference: str, *, count: int = 0) -> None:
            paths = resolve_runtime_card_paths(
                self.resource_root,
                reference,
                exact_index=self._exact_index,
                stem_index=self._stem_index,
                variant_index=self._variant_index,
            )
            if not paths:
                missing.append(reference)
                return
            if count > 0:
                try:
                    cost, _enhance, _name = parse_card_filename(
                        os.path.basename(paths[0])
                    )
                    costs[int(cost or 0)] += int(count)
                except Exception:
                    costs[0] += int(count)
            for source in paths:
                destination = os.path.basename(source)
                key = destination.casefold()
                previous = source_by_destination.get(key)
                if previous and os.path.normcase(previous) != os.path.normcase(source):
                    raise DeckProfileError(f"卡牌模板文件名冲突: {destination}")
                source_by_destination[key] = source

        for record in cards:
            collect(
                str(record.get("card_id") or ""),
                count=max(0, int(record.get("count") or 0)),
            )
        for record in derived_cards:
            collect(str(record.get("card_id") or ""))

        if missing:
            unique_missing = list(dict.fromkeys(missing))
            raise DeckProfileError(
                "卡牌资源不完整: " + ", ".join(unique_missing[:8])
            )
        if not source_by_destination:
            raise DeckProfileError(f"本地构筑没有可用识别模板: {safe_name}")

        temp_dir = tempfile.TemporaryDirectory(prefix="sv-auto-deck-")
        try:
            for source in source_by_destination.values():
                shutil.copy2(source, os.path.join(temp_dir.name, os.path.basename(source)))
            recognizer = SiftCardRecognition(temp_dir.name)
            if not recognizer.card_templates:
                raise DeckProfileError(f"构筑模板无法提取 SIFT 特征: {safe_name}")
            strategy_config = extract_deck_strategy_config(data)
            strategy_config.setdefault("high_priority_cards", {})
            strategy_config.setdefault("evolve_priority_cards", {})
            strategy = strategy_config.setdefault("strategy", {})
            if not isinstance(strategy, dict):
                strategy = {}
                strategy_config["strategy"] = strategy
            strategy.setdefault("effects", {})

            profile = RuntimeDeckProfile(
                filename=safe_name,
                name=str(data.get("name") or os.path.splitext(safe_name)[0]).strip()
                or os.path.splitext(safe_name)[0],
                strategy_config=strategy_config,
                template_dir=temp_dir.name,
                recognizer=recognizer,
                card_count=sum(max(0, int(item.get("count") or 0)) for item in cards),
                distinct_count=len(cards),
                derived_count=len(derived_cards),
                costs=dict(sorted(costs.items())),
                _temporary_dir=temp_dir,
            )
        except Exception:
            temp_dir.cleanup()
            raise

        self._cache[cache_key] = profile
        return profile

    def close(self) -> None:
        for profile in list(self._cache.values()):
            profile.close()
        self._cache.clear()
