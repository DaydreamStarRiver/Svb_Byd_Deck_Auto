"""Card filename helpers.

Support Enhance/"爆能" tiers encoded in image filenames.

Naming convention (stem without extension):
- "4_xxx" -> base_cost=4, enhance_costs=[], name="xxx"
- "4@6_xxx" -> base_cost=4, enhance_costs=[6], name="xxx"
- "4@6@8_xxx" -> base_cost=4, enhance_costs=[6, 8], name="xxx"
- Legacy "4_6_xxx" / "4_6_8_xxx" is also accepted.

Card names may contain underscores. Enhance tiers are parsed as @-separated
integer segments immediately after the base cost.

Card names are resolved from CSV file when the parsed name looks like a card ID.
"""

from __future__ import annotations

import csv
import os
import re
from typing import Dict, List, Optional, Tuple

# Global card ID to name mapping, loaded on first access
_CARD_ID_MAP: Dict[str, str] = {}


def _get_app_root() -> str:
    """Get the application root directory.

    In packaged (EXE) mode, returns the directory containing the EXE.
    In development mode, returns the project root directory.
    """
    import sys

    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        return os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )


def _find_csv_path() -> str:
    """Find the CSV file path with multiple fallback locations."""
    import sys

    app_root = _get_app_root()

    possible_paths = [
        os.path.join(app_root, "quanka\SV_WB_Cards", "SV_WB_Cards.csv"),
        os.path.join(app_root, "SV_WB_Cards.csv"),
        os.path.join(os.path.dirname(app_root), "quanka\SV_WB_Cards", "SV_WB_Cards.csv"),
    ]

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        possible_paths.extend(
            [
                os.path.join(exe_dir, "quanka\SV_WB_Cards", "SV_WB_Cards.csv"),
                os.path.join(exe_dir, "SV_WB_Cards.csv"),
            ]
        )

    for path in possible_paths:
        if os.path.exists(path):
            return os.path.abspath(path)

    return possible_paths[0]


def _load_card_id_map() -> Dict[str, str]:
    """Load card ID to name mapping from CSV file."""
    if _CARD_ID_MAP:
        return _CARD_ID_MAP

    csv_path = _find_csv_path()

    if not os.path.exists(csv_path):
        return {}

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                card_id = row.get("card_id", "").strip()
                card_name = row.get("name", "").strip()
                if card_id and card_name:
                    _CARD_ID_MAP[card_id] = card_name
    except Exception:
        pass

    return _CARD_ID_MAP


def get_card_name_by_id(card_id: str) -> Optional[str]:
    """Get card name from card ID using CSV mapping."""
    return _load_card_id_map().get(str(card_id).strip())


def _basename_stem(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    s = s.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in s:
        s = s.rsplit(".", 1)[0]
    return str(s or "")


def is_evo_card_name(card_name: str) -> bool:
    """Return True when name/stem/filename ends with ``_evo``."""

    stem = _basename_stem(card_name)
    if not stem:
        return False
    return stem.lower().endswith("_evo")


def strip_evo_suffix(card_name: str) -> str:
    """Strip a trailing ``_evo`` suffix from a card name/stem."""

    raw = str(card_name or "").strip()
    if not raw:
        return ""
    if raw.lower().endswith("_evo"):
        return raw[:-4]
    return raw


def parse_follower_stat_suffix(card_name: str) -> Tuple[str, Optional[int], Optional[int]]:
    """Parse follower stat suffix from a card name.

    Expected suffix format: ``..._<atk>_<hp>``.
    Parsing is done from the rightmost two underscore segments.

    Returns:
        (base_name, base_atk, base_hp)
        - On success: base_name excludes the trailing ``_<atk>_<hp>``.
        - On failure: base_name is the original name, atk/hp are None.
    """

    raw = str(card_name or "").strip()
    if not raw:
        return "", None, None

    parts = raw.split("_")
    if len(parts) < 3:
        return raw, None, None

    atk_s = parts[-2]
    hp_s = parts[-1]
    if not (atk_s.isdigit() and hp_s.isdigit()):
        return raw, None, None

    base_name = "_".join(parts[:-2]).strip()
    if not base_name:
        return raw, None, None

    try:
        return base_name, int(atk_s), int(hp_s)
    except Exception:
        return raw, None, None


def normalize_card_base_name(card_name: str) -> str:
    """Return a stable card base name used by UI/config keys.

    - Removes follower stat suffix ``_<atk>_<hp>`` when present.
    - Removes evolve image suffix ``_evo`` when present.
    - Keeps original text when suffix is absent.
    """

    raw = str(card_name or "").strip()
    if not raw:
        return ""

    no_evo = strip_evo_suffix(raw)
    base, _atk, _hp = parse_follower_stat_suffix(no_evo)
    normalized = str(base or no_evo)
    return strip_evo_suffix(normalized)


def normalize_config_key(key: str) -> str:
    """Normalize a strategy/config key to suffix-free base naming.

    Supports both plain keys and enhance keys (``name@cost``).
    """

    raw = str(key or "").strip()
    if not raw:
        return ""

    base, enhance = split_enhance_key(raw)
    normalized_base = normalize_card_base_name(str(base or ""))
    if enhance is None:
        return normalized_base
    return make_enhance_key(normalized_base, int(enhance))


def parse_card_stem(stem: str) -> Tuple[int, List[int], str]:
    """Parse a card filename stem.

    Args:
        stem: filename without extension.

    Returns:
        (base_cost, enhance_costs, card_name)
    """

    stem = str(stem or "").strip()
    if not stem:
        return 0, [], ""

    # Handle new format: "2@4@6_xxx" (base_cost@enhance1@enhance2_name)
    # Split by underscore first to separate cost part from name part
    parts = stem.split("_")
    if not parts:
        return 0, [], stem

    # Parse cost part (may contain @ for enhance tiers)
    cost_part = parts[0]
    cost_segments = cost_part.split("@")

    try:
        base_cost = int(cost_segments[0])
    except Exception:
        # Fallback: treat whole stem as name.
        return 0, [], stem

    # Parse enhance tiers from @-separated segments
    enhance_raw: List[int] = []
    for seg in cost_segments[1:]:
        try:
            enhance_raw.append(int(seg))
        except Exception:
            break

    # The rest are name parts. Also accept the legacy underscore format:
    # "4_6_name" / "4_6_8_name". To avoid misreading numeric card IDs like
    # "4_10001110" as enhance tiers, only consume underscore enhance segments
    # while at least one following segment remains as the card name.
    name_start = 1
    if len(cost_segments) == 1:
        for idx in range(1, len(parts) - 1):
            seg = parts[idx]
            try:
                enhance_raw.append(int(seg))
                name_start = idx + 1
                continue
            except Exception:
                break

    name_parts = parts[name_start:]

    card_name = "_".join([p for p in name_parts if p is not None])
    if not card_name:
        # If name is missing, best-effort fallback to stem tail.
        card_name = stem.split("_", 1)[-1] if "_" in stem else stem

    # Try to resolve card ID to real name from CSV
    # Check if card_name looks like a card ID (8-digit number)
    resolved_name = _resolve_card_name(card_name)
    if resolved_name:
        card_name = resolved_name

    # Normalize enhance tiers: unique, > base_cost, sorted ascending.
    enhance_costs: List[int] = []
    for c in enhance_raw:
        try:
            c = int(c)
        except Exception:
            continue
        if c <= base_cost:
            continue
        if c not in enhance_costs:
            enhance_costs.append(c)
    enhance_costs.sort()

    return int(base_cost), enhance_costs, str(card_name)


def _resolve_card_name(card_name: str) -> Optional[str]:
    """Resolve card name from card ID if it looks like an ID.

    Card IDs are typically 8-digit numbers. If the parsed name is purely numeric,
    try to look it up in the CSV mapping.

    Also supports alternate art format: "10001110@1" -> resolves "10001110@1" from CSV
    If alternate art is not found in CSV, falls back to base card ID.
    """
    card_name = str(card_name or "").strip()
    if not card_name:
        return None

    # Check if it looks like a card ID (8-digit number)
    if card_name.isdigit() and len(card_name) == 8:
        return get_card_name_by_id(card_name)

    # Check if it looks like alternate art format: "10001110@1"
    alt_art_pattern = re.match(r"^(\d{8})@(\d+)$", card_name)
    if alt_art_pattern:
        # First try to find the alternate art entry
        resolved = get_card_name_by_id(card_name)
        if resolved:
            return resolved
        # Fallback to base card ID
        base_id = alt_art_pattern.group(1)
        return get_card_name_by_id(base_id)

    # Also check if it ends with atk_hp suffix (e.g., "10001110_2_2")
    # Strip the stat suffix to get the base ID
    parts = card_name.split("_")
    if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
        potential_id = "_".join(parts[:-2])
        if potential_id.isdigit() and len(potential_id) == 8:
            return get_card_name_by_id(potential_id)

        # Also check alternate art format with stat suffix (e.g., "10001110@1_2_3")
        alt_art_pattern = re.match(r"^(\d{8})@(\d+)$", potential_id)
        if alt_art_pattern:
            # First try to find the alternate art entry
            resolved = get_card_name_by_id(potential_id)
            if resolved:
                return resolved
            # Fallback to base card ID
            base_id = alt_art_pattern.group(1)
            return get_card_name_by_id(base_id)

    return None


def parse_card_filename(filename: str) -> Tuple[int, List[int], str]:
    """Parse a card image filename (with extension)."""

    name = str(filename or "")
    stem = name.rsplit(".", 1)[0]
    return parse_card_stem(stem)


def make_enhance_key(card_name: str, enhance_cost: int) -> str:
    """Build a config key for an enhance-tier variant."""

    return f"{str(card_name)}@{int(enhance_cost)}"


def split_enhance_key(key: str) -> Tuple[str, Optional[int]]:
    """Split a config key into (base_name, enhance_cost)."""

    s = str(key or "")
    if "@" not in s:
        return s, None
    base, tail = s.rsplit("@", 1)
    try:
        return base, int(tail)
    except Exception:
        return s, None
