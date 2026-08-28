"""由外部 ``quanka`` 资源驱动的卡牌目录模型。"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple, Union

from src.config.paths import get_app_root


CARD_CATEGORIES: Tuple[str, ...] = (
    "\u4e2d\u7acb",
    "\u5996\u7cbe",
    "\u7687\u5bb6",
    "\u6cd5\u5e08",
    "\u9f99\u65cf",
    "\u68a6\u9b47",
    "\u4e3b\u6559",
    "\u8d85\u8d8a\u8005",
)
SUPPORTED_IMAGE_EXTENSIONS: Tuple[str, ...] = (
    ".webp",
    ".png",
    ".jpg",
    ".jpeg",
)

_CARD_FILENAME_RE = re.compile(
    r"^(?P<cost>\d+(?:@\d+)*)_"
    r"(?P<card_id>\d{8}(?:@\d+)?)"
    r"(?:(?:_(?P<atk>\d+)_(?P<hp>\d+))|(?:_evo))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CardEntry:
    """目录中一张可选择的非进化卡图。"""

    key: str
    card_id: str
    cost: int
    enhance_costs: Tuple[int, ...]
    name: str
    category: str
    source_path: str
    relative_path: str
    card_set_id: str = ""
    card_set_name: str = "其他"
    rarity: int = 0
    rarity_name: str = "其他"
    card_type: int = 0
    card_type_name: str = "其他"
    is_token: bool = False

    @property
    def filename(self) -> str:
        """返回卡组 IO 使用的实际源文件名。"""

        return os.path.basename(self.source_path)


def _looks_like_resource_root(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    if os.path.isfile(os.path.join(path, "SV_WB_Cards.csv")):
        return True
    return any(os.path.isdir(os.path.join(path, category)) for category in CARD_CATEGORIES)


def get_card_resource_root(app_root: Optional[str] = None) -> str:
    """返回源码或打包运行时的卡牌资源根目录。

    当前子模块结构为 ``quanka/SV_WB_Cards``。旧版本曾将 CSV 和职业目录直接放在
    ``quanka`` 下，仅当当前结构不存在时才使用旧位置。
    """

    root = os.path.abspath(app_root or get_app_root())
    current = os.path.join(root, "quanka", "SV_WB_Cards")
    if os.path.isdir(current):
        return current

    legacy = os.path.join(root, "quanka")
    if _looks_like_resource_root(legacy):
        return legacy
    return current


@dataclass(frozen=True)
class CardMetadata:
    cost: int
    name: str
    card_set_id: str = ""
    card_set_name: str = "其他"
    rarity: int = 0
    rarity_name: str = "其他"
    card_type: int = 0
    card_type_name: str = "其他"
    is_token: bool = False


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value or default).strip())
    except (TypeError, ValueError):
        return int(default)


def _load_card_metadata(resource_root: str) -> Dict[str, CardMetadata]:
    csv_path = os.path.join(resource_root, "SV_WB_Cards.csv")
    if not os.path.isfile(csv_path):
        return {}

    metadata: Dict[str, CardMetadata] = {}
    try:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                card_id = str(row.get("card_id") or "").strip()
                name = str(row.get("name") or "").strip()
                if not card_id:
                    continue
                metadata[card_id] = CardMetadata(
                    cost=_safe_int(row.get("cost")),
                    name=name or card_id,
                    card_set_id=str(row.get("card_set_id") or "").strip(),
                    card_set_name=str(row.get("card_set_name") or "其他").strip()
                    or "其他",
                    rarity=_safe_int(row.get("rarity")),
                    rarity_name=str(row.get("rarity_name") or "其他").strip()
                    or "其他",
                    card_type=_safe_int(row.get("card_type")),
                    card_type_name=str(row.get("card_type_name") or "其他").strip()
                    or "其他",
                    is_token=str(row.get("is_token") or "").strip().casefold()
                    in {"1", "true", "yes"},
                )
    except (OSError, csv.Error, UnicodeError):
        return {}
    return metadata


def _category_sort_key(category: str) -> Tuple[int, str]:
    try:
        return CARD_CATEGORIES.index(category), ""
    except ValueError:
        return len(CARD_CATEGORIES), category.casefold()


def load_card_catalog(resource_root: Optional[str] = None) -> List[CardEntry]:
    """读取元数据并返回全部可选择的非进化卡图。"""

    root = os.path.abspath(resource_root or get_card_resource_root())
    if not os.path.isdir(root):
        return []

    metadata = _load_card_metadata(root)
    entries: List[CardEntry] = []

    try:
        category_names = [
            item.name
            for item in os.scandir(root)
            if item.is_dir(follow_symlinks=False)
        ]
    except OSError:
        return []

    category_names.sort(key=_category_sort_key)
    for category in category_names:
        category_path = os.path.join(root, category)
        try:
            files = sorted(os.scandir(category_path), key=lambda item: item.name.casefold())
        except OSError:
            continue

        for item in files:
            if not item.is_file(follow_symlinks=False):
                continue
            stem, extension = os.path.splitext(item.name)
            if extension.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
                continue
            if stem.lower().endswith("_evo"):
                continue

            match = _CARD_FILENAME_RE.fullmatch(stem)
            if match is None:
                continue

            cost_parts = tuple(int(part) for part in match.group("cost").split("@"))
            filename_cost = cost_parts[0]
            enhance_costs = tuple(
                sorted({cost for cost in cost_parts[1:] if cost > filename_cost})
            )
            card_id = match.group("card_id")
            card_metadata = metadata.get(
                card_id,
                metadata.get(
                    card_id.split("@", 1)[0],
                    CardMetadata(filename_cost, card_id),
                ),
            )
            relative_path = os.path.relpath(item.path, root).replace(os.sep, "/")
            entries.append(
                CardEntry(
                    key=f"{category}/{card_id}",
                    card_id=card_id,
                    cost=card_metadata.cost,
                    enhance_costs=enhance_costs,
                    name=card_metadata.name,
                    category=category,
                    source_path=os.path.abspath(item.path),
                    relative_path=relative_path,
                    card_set_id=card_metadata.card_set_id,
                    card_set_name=card_metadata.card_set_name,
                    rarity=card_metadata.rarity,
                    rarity_name=card_metadata.rarity_name,
                    card_type=card_metadata.card_type,
                    card_type_name=card_metadata.card_type_name,
                    is_token=card_metadata.is_token,
                )
            )

    entries.sort(
        key=lambda entry: (
            _category_sort_key(entry.category),
            entry.cost,
            entry.name.casefold(),
            entry.card_id.casefold(),
            entry.relative_path.casefold(),
        )
    )
    return entries


def _reference_forms(reference: str) -> Tuple[str, str, str, str]:
    raw = str(reference or "").strip()
    slash_path = raw.replace("\\", "/").strip("/")
    basename = slash_path.rsplit("/", 1)[-1]
    stem = os.path.splitext(basename)[0]
    return raw, slash_path.casefold(), basename.casefold(), stem.casefold()


def resolve_card_entry(
    reference: Union[str, CardEntry],
    catalog: Optional[Iterable[CardEntry]] = None,
    resource_root: Optional[str] = None,
) -> Optional[CardEntry]:
    """将持久化或界面卡牌引用解析为一个目录条目。

    支持稳定键、相对路径、绝对源路径、文件名、主文件名和卡牌 ID；显示名称可能
    存在歧义，因此特意不将其作为引用依据。
    """

    if isinstance(reference, CardEntry):
        return reference

    raw, slash_path, basename, stem = _reference_forms(reference)
    if not raw:
        return None

    entries = list(catalog) if catalog is not None else load_card_catalog(resource_root)
    normalized_absolute = os.path.normcase(os.path.abspath(raw))

    for entry in entries:
        if slash_path in (entry.key.casefold(), entry.relative_path.casefold()):
            return entry
        if normalized_absolute == os.path.normcase(os.path.abspath(entry.source_path)):
            return entry

    filename_matches = [
        entry
        for entry in entries
        if basename == entry.filename.casefold()
        or stem == os.path.splitext(entry.filename)[0].casefold()
    ]
    if len(filename_matches) == 1:
        return filename_matches[0]

    card_id_matches = [entry for entry in entries if slash_path == entry.card_id.casefold()]
    if len(card_id_matches) == 1:
        return card_id_matches[0]
    return None
