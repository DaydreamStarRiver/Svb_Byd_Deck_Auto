"""ConfigRepository: single write point for UI-facing config I/O.

UI pages previously wrote config.json directly in multiple places, causing
inconsistent migrations and partial schema restores (e.g. deck snapshots).

This module keeps the UI's needs simple:
- Load existing config.json (optionally refusing to overwrite on parse errors)
- Apply deep-merge patches while preserving unknown/hidden fields
- Normalize against DEFAULT_CONFIG and run migrations before writing
- Persist via atomic write (temp + os.replace)
"""

from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.config.io_guard import is_in_battle
from src.config.migrations import (
    migrate_high_priority_cards_priority_fields,
    migrate_runtime_legacy_fields,
    migrate_strategy_name_keys,
    migrate_strategy_effects_schema,
    migrate_strategy_split_attack_times_buff,
    migrate_strategy_effects_to_ops,
    prune_invalid_strategy_effect_ops,
)
from src.config.paths import get_config_path
from src.config.persisted_config import prune_config_for_save
from src.config.settings import DEFAULT_CONFIG
from src.core.json_io import write_json_atomic

logger = logging.getLogger(__name__)


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Return a merged copy of base with patch applied (recursive for dicts).

    - Dicts are merged recursively.
    - Lists/values in patch replace base.
    - Nested containers are deep-copied to avoid reference sharing.
    """

    merged: Dict[str, Any] = copy.deepcopy(base) if isinstance(base, dict) else {}
    if not isinstance(patch, dict):
        return merged

    for k, v in patch.items():
        if k in merged and isinstance(merged.get(k), dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
            continue
        if isinstance(v, (dict, list)):
            merged[k] = copy.deepcopy(v)
        else:
            merged[k] = v
    return merged


def _normalize_and_migrate(user_config: Dict[str, Any]) -> Dict[str, Any]:
    """Merge against DEFAULT_CONFIG and apply schema migrations."""

    cfg = _deep_merge(DEFAULT_CONFIG, user_config if isinstance(user_config, dict) else {})
    try:
        migrate_high_priority_cards_priority_fields(cfg)
    except Exception:
        pass
    try:
        migrate_strategy_name_keys(cfg)
    except Exception:
        pass
    try:
        migrate_strategy_effects_schema(cfg)
    except Exception:
        pass
    try:
        migrate_strategy_effects_to_ops(cfg)
    except Exception:
        pass
    try:
        migrate_strategy_split_attack_times_buff(cfg)
    except Exception:
        pass
    try:
        prune_invalid_strategy_effect_ops(cfg)
    except Exception:
        pass
    try:
        migrate_runtime_legacy_fields(cfg)
    except Exception:
        pass
    return cfg


@dataclass(frozen=True)
class ConfigWriteResult:
    ok: bool
    parse_ok: bool
    error: Optional[str] = None


class ConfigRepository:
    """Repository-style helper for config.json I/O used by UI."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = os.path.abspath(config_path or get_config_path())

    def load_existing(
        self, *, allow_default_on_error: bool = True
    ) -> tuple[Optional[Dict[str, Any]], bool, Optional[str]]:
        """Load config.json from disk.

        Returns: (config_or_none, parse_ok, error)
        - If file is missing: returns normalized defaults, parse_ok=True.
        - If JSON parse fails and allow_default_on_error=True: returns normalized defaults, parse_ok=False.
        - If JSON parse fails and allow_default_on_error=False: returns None, parse_ok=False.
        """

        if not os.path.exists(self.config_path):
            return _normalize_and_migrate({}), True, None

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raw = {}
            return _normalize_and_migrate(raw), True, None
        except Exception as e:
            if not allow_default_on_error:
                return None, False, str(e)
            return _normalize_and_migrate({}), False, str(e)

    def save(
        self,
        config: Dict[str, Any],
        *,
        indent: int = 2,
        ensure_ascii: bool = False,
    ) -> ConfigWriteResult:
        if is_in_battle():
            logger.warning("[IO] battle context: saving config to disk: %s", self.config_path)
        try:
            write_json_atomic(
                self.config_path,
                prune_config_for_save(config),
                indent=indent,
                ensure_ascii=ensure_ascii,
            )
            return ConfigWriteResult(ok=True, parse_ok=True, error=None)
        except Exception as e:
            return ConfigWriteResult(ok=False, parse_ok=True, error=str(e))

    def update(
        self,
        patch: Dict[str, Any],
        *,
        refuse_on_parse_error: bool = False,
        indent: int = 2,
        ensure_ascii: bool = False,
    ) -> ConfigWriteResult:
        existing, parse_ok, err = self.load_existing(
            allow_default_on_error=not refuse_on_parse_error
        )
        if existing is None:
            return ConfigWriteResult(ok=False, parse_ok=False, error=err or "config.json parse failed")

        merged = _deep_merge(existing, patch if isinstance(patch, dict) else {})
        normalized = _normalize_and_migrate(merged)
        res = self.save(normalized, indent=indent, ensure_ascii=ensure_ascii)
        # Preserve parse_ok from initial load for callers that care.
        return ConfigWriteResult(ok=res.ok, parse_ok=parse_ok, error=res.error or err)

    def replace_with_snapshot(
        self,
        snapshot_config: Dict[str, Any],
        *,
        indent: int = 2,
        ensure_ascii: bool = False,
    ) -> ConfigWriteResult:
        normalized = _normalize_and_migrate(snapshot_config if isinstance(snapshot_config, dict) else {})
        return self.save(normalized, indent=indent, ensure_ascii=ensure_ascii)
