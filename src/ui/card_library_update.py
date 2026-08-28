"""官方卡牌库差异检查与低频、原子化增量更新。"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

import requests
from PIL import Image

from src.core.json_io import write_text_atomic


API_URL = "https://shadowverse-wb.com/web/CardList/cardList"
IMAGE_URL = "https://shadowverse-wb.com/uploads/card_image/chs/card/{image_hash}.png"
CLASS_NAMES = {
    0: "中立",
    1: "妖精",
    2: "皇家",
    3: "法师",
    4: "龙族",
    5: "梦魇",
    6: "主教",
    7: "超越者",
}
RARITY_NAMES = {1: "青铜", 2: "白银", 3: "黄金", 4: "传说"}
TYPE_NAMES = {1: "随从", 2: "护符", 3: "护符", 4: "法术"}
CSV_FIELDS = (
    "card_id",
    "cost",
    "name",
    "card_set_id",
    "card_set_name",
    "rarity",
    "rarity_name",
    "card_type",
    "card_type_name",
    "class_id",
    "category",
    "is_token",
    "atk",
    "life",
    "file_cost",
    "image_hash",
    "evo_image_hash",
)
BURST_PATTERN = re.compile(r"爆能强化</color>_(\d+)")
LOCAL_CARD_RE = re.compile(
    r"^(?P<file_cost>\d+(?:@\d+)*)_"
    r"(?P<card_id>\d{8}(?:@\d+)?)"
    r"(?:(?:_(?P<atk>\d+)_(?P<life>\d+))|(?:_evo))?$",
    re.IGNORECASE,
)
_PLAN_CACHE: Dict[str, tuple[float, CardLibraryUpdatePlan]] = {}
_PLAN_CACHE_LOCK = threading.Lock()


class CardLibraryUpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class CardAsset:
    card_id: str
    category: str
    filename: str
    image_hash: str
    kind: str

    @property
    def relative_path(self) -> str:
        return f"{self.category}/{self.filename}"


@dataclass(frozen=True)
class CardLibraryUpdatePlan:
    resource_root: str
    rows: Tuple[Dict[str, str], ...]
    assets: Tuple[CardAsset, ...]
    remote_card_count: int
    local_row_count: int
    remote_set_names: Dict[str, str]
    new_sets: Tuple[Tuple[str, str], ...]
    missing_assets: Tuple[CardAsset, ...]
    changed_assets: Tuple[CardAsset, ...]
    metadata_changed: bool

    @property
    def download_assets(self) -> Tuple[CardAsset, ...]:
        combined = {}
        for asset in (*self.missing_assets, *self.changed_assets):
            combined[asset.relative_path.casefold()] = asset
        return tuple(combined.values())

    @property
    def has_updates(self) -> bool:
        return bool(self.download_assets or self.metadata_changed)


def _read_csv_rows(path: str) -> list[Dict[str, str]]:
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as stream:
            return [
                {str(key): str(value or "") for key, value in row.items() if key}
                for row in csv.DictReader(stream)
            ]
    except (OSError, UnicodeError, csv.Error):
        return []


def _normalized_row(row: Dict[str, Any]) -> Dict[str, str]:
    normalized = {}
    for field in CSV_FIELDS:
        value = row.get(field, "")
        normalized[field] = "" if value is None else str(value)
    return normalized


def _csv_text(rows: Iterable[Dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(CSV_FIELDS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(_normalized_row(row))
    return output.getvalue()


def _file_cost(common: Dict[str, Any]) -> str:
    cost = int(common.get("cost", 0) or 0)
    values = BURST_PATTERN.findall(str(common.get("skill_text") or ""))
    return "@".join([str(cost), *values]) if values else str(cost)


def _variant_row(
    *,
    card_id: str,
    name: str,
    common: Dict[str, Any],
    set_names: Dict[str, str],
    image_hash: str,
    evo_image_hash: str,
) -> Dict[str, str]:
    class_id = int(common.get("class", 0) or 0)
    rarity = int(common.get("rarity", 0) or 0)
    card_type = int(common.get("type", 0) or 0)
    set_id = str(common.get("card_set_id") or "")
    is_token = bool(common.get("is_token", False))
    set_name = "Token / 衍生物" if is_token or set_id == "90000" else set_names.get(
        set_id,
        set_id or "其他",
    )
    return _normalized_row(
        {
            "card_id": card_id,
            "cost": int(common.get("cost", 0) or 0),
            "name": name or card_id,
            "card_set_id": set_id,
            "card_set_name": set_name,
            "rarity": rarity,
            "rarity_name": RARITY_NAMES.get(rarity, "其他"),
            "card_type": card_type,
            "card_type_name": TYPE_NAMES.get(card_type, "其他"),
            "class_id": class_id,
            "category": CLASS_NAMES.get(class_id, "中立"),
            "is_token": "1" if is_token else "0",
            "atk": int(common.get("atk", 0) or 0),
            "life": int(common.get("life", 0) or 0),
            "file_cost": _file_cost(common),
            "image_hash": image_hash,
            "evo_image_hash": evo_image_hash,
        }
    )


def _assets_for_row(row: Dict[str, str]) -> list[CardAsset]:
    card_id = row["card_id"]
    cost = row.get("file_cost") or row.get("cost") or "0"
    category = row.get("category") or "中立"
    card_type = int(row.get("card_type") or 0)
    atk = int(row.get("atk") or 0)
    life = int(row.get("life") or 0)
    assets = []
    image_hash = row.get("image_hash", "")
    if image_hash:
        if card_type == 1:
            filename = f"{cost}_{card_id}_{atk}_{life}.webp"
        else:
            filename = f"{cost}_{card_id}.webp"
        assets.append(CardAsset(card_id, category, filename, image_hash, "base"))
    evo_hash = row.get("evo_image_hash", "")
    if evo_hash:
        assets.append(
            CardAsset(card_id, category, f"{cost}_{card_id}_evo.webp", evo_hash, "evo")
        )
    return assets


def _discover_local_rows(
    resource_root: str,
    known_rows: Dict[str, Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    """从已有非进化文件恢复官网本轮未返回的旧异画条目。"""

    discovered: Dict[str, Dict[str, str]] = {}
    try:
        categories = [item for item in os.scandir(resource_root) if item.is_dir()]
    except OSError:
        return discovered
    for category_item in categories:
        try:
            files = os.scandir(category_item.path)
        except OSError:
            continue
        with files:
            for item in files:
                if not item.is_file() or not item.name.casefold().endswith(
                    (".webp", ".png", ".jpg", ".jpeg")
                ):
                    continue
                stem = os.path.splitext(item.name)[0]
                if stem.casefold().endswith("_evo"):
                    continue
                match = LOCAL_CARD_RE.fullmatch(stem)
                if match is None:
                    continue
                card_id = match.group("card_id")
                if card_id in known_rows or card_id in discovered:
                    continue
                base_id = card_id.split("@", 1)[0]
                base = known_rows.get(base_id)
                if base is None:
                    continue
                row = dict(base)
                row.update(
                    {
                        "card_id": card_id,
                        "name": row.get("name") or card_id,
                        "cost": match.group("file_cost").split("@", 1)[0],
                        "file_cost": match.group("file_cost"),
                        "category": category_item.name,
                        "atk": match.group("atk") or row.get("atk", "0"),
                        "life": match.group("life") or row.get("life", "0"),
                        # 哈希不可从 WebP 反推，保留为空；文件本身继续被目录加载。
                        "image_hash": "",
                        "evo_image_hash": "",
                    }
                )
                discovered[card_id] = _normalized_row(row)
    return discovered


class OfficialCardLibraryClient:
    """单线程、带退避的官方图鉴客户端；仅由用户手动触发。"""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        request_interval: float = 0.2,
        progress: Optional[Callable[[str], None]] = None,
        cancelled: Optional[Callable[[], bool]] = None,
    ):
        self.timeout = max(5.0, float(timeout))
        self.request_interval = max(0.1, float(request_interval))
        self.progress = progress or (lambda _message: None)
        self.cancelled = cancelled or (lambda: False)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "accept": "application/json, text/plain, */*",
                "lang": "chs",
                "User-Agent": "SV-Auto-CardLibrary/1.0 (+manual update)",
                "referer": "https://shadowverse-wb.com/chs/deck/cardslist/",
            }
        )
        self._last_request = 0.0

    def close(self) -> None:
        self.session.close()

    def _check_cancelled(self) -> None:
        if self.cancelled():
            raise CardLibraryUpdateError("用户取消了卡牌库更新")

    def _request(self, url: str, *, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        last_error: Optional[Exception] = None
        for attempt in range(3):
            self._check_cancelled()
            wait = self.request_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                self._last_request = time.monotonic()
                if response.status_code == 429:
                    retry_after = min(30.0, float(response.headers.get("Retry-After", 2) or 2))
                    time.sleep(retry_after)
                    continue
                response.raise_for_status()
                return response
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        raise CardLibraryUpdateError(f"官方资源请求失败: {last_error}")

    def fetch_plan(
        self,
        resource_root: str,
        *,
        cache_ttl_seconds: float = 900.0,
    ) -> CardLibraryUpdatePlan:
        root = os.path.abspath(resource_root)
        cache_key = os.path.normcase(root)
        ttl = max(0.0, float(cache_ttl_seconds))
        if ttl > 0:
            with _PLAN_CACHE_LOCK:
                cached = _PLAN_CACHE.get(cache_key)
            if cached is not None and (time.monotonic() - cached[0]) <= ttl:
                self.progress("使用本次运行内的官方清单缓存，避免重复请求")
                return cached[1]
        csv_path = os.path.join(root, "SV_WB_Cards.csv")
        local_rows = _read_csv_rows(csv_path)
        old_by_id = {
            str(row.get("card_id") or ""): _normalized_row(row)
            for row in local_rows
            if str(row.get("card_id") or "")
        }
        merged = dict(old_by_id)
        remote_rows: Dict[str, Dict[str, str]] = {}
        assets: Dict[str, CardAsset] = {}
        set_names: Dict[str, str] = {}
        offset = 0
        expected_count = 0
        while True:
            self.progress(f"正在读取官方卡牌清单：{offset} / {expected_count or '?'}")
            response = self._request(
                API_URL,
                params={
                    "include_token": 1,
                    "offset": offset,
                    "class": "0,1,2,3,4,5,6,7",
                    "cost": "0,1,2,3,4,5,6,7,8,9,10",
                },
            )
            try:
                payload = json.loads(response.content.decode("utf-8"))
                data = payload.get("data", {})
            except Exception as exc:
                raise CardLibraryUpdateError(f"官方清单响应格式错误: {exc}") from exc
            if not isinstance(data, dict):
                raise CardLibraryUpdateError("官方清单缺少 data")
            set_names.update(
                {
                    str(key): str(value or key)
                    for key, value in dict(data.get("card_set_names") or {}).items()
                }
            )
            expected_count = max(expected_count, int(data.get("count", 0) or 0))
            ids = list(data.get("sort_card_id_list") or [])
            if not ids:
                break
            details = data.get("card_details", {})
            for raw_id in ids:
                detail = details.get(str(raw_id), {}) if isinstance(details, dict) else {}
                common = detail.get("common", {}) if isinstance(detail, dict) else {}
                if not isinstance(common, dict):
                    continue
                base_id = str(common.get("card_id") or raw_id)
                evo = detail.get("evo", {})
                evo_hash = (
                    str(evo.get("card_image_hash") or "") if isinstance(evo, dict) else ""
                )
                base_row = _variant_row(
                    card_id=base_id,
                    name=str(common.get("name") or base_id),
                    common=common,
                    set_names=set_names,
                    image_hash=str(common.get("card_image_hash") or ""),
                    evo_image_hash=evo_hash,
                )
                remote_rows[base_id] = base_row
                for asset in _assets_for_row(base_row):
                    assets[asset.relative_path.casefold()] = asset
                styles = detail.get("style_card_list", [])
                if isinstance(styles, list):
                    for index, style in enumerate(styles, start=1):
                        if not isinstance(style, dict):
                            continue
                        style_id = f"{base_id}@{index}"
                        old_name = old_by_id.get(style_id, {}).get("name", "")
                        style_row = _variant_row(
                            card_id=style_id,
                            name=str(style.get("name") or old_name or common.get("name") or style_id),
                            common=common,
                            set_names=set_names,
                            image_hash=str(style.get("hash") or ""),
                            evo_image_hash=str(style.get("evo_hash") or ""),
                        )
                        remote_rows[style_id] = style_row
                        for asset in _assets_for_row(style_row):
                            assets[asset.relative_path.casefold()] = asset
            offset += len(ids)
            if expected_count > 0 and offset >= expected_count:
                break

        if not remote_rows:
            raise CardLibraryUpdateError("官方卡牌清单为空，已拒绝更新本地数据")

        # 官方清单偶尔不返回旧珍藏异画。保留本地条目，并从基础卡继承可确定的
        # 卡包/稀有度/类型信息；异画自己的图片哈希未知，不能伪造。
        for card_id, old_row in list(old_by_id.items()):
            if card_id in remote_rows or "@" not in card_id:
                continue
            base_id = card_id.split("@", 1)[0]
            base_row = remote_rows.get(base_id)
            if base_row is None:
                continue
            inherited = dict(base_row)
            inherited.update(
                {
                    "card_id": card_id,
                    "name": old_row.get("name") or base_row.get("name") or card_id,
                    "cost": old_row.get("cost") or base_row.get("cost") or "0",
                    "image_hash": old_row.get("image_hash", ""),
                    "evo_image_hash": old_row.get("evo_image_hash", ""),
                }
            )
            merged[card_id] = _normalized_row(inherited)
        merged.update(remote_rows)
        known_for_discovery = dict(merged)
        known_for_discovery.update(remote_rows)
        merged.update(_discover_local_rows(root, known_for_discovery))
        rows = tuple(
            merged[key]
            for key in sorted(
                merged,
                key=lambda value: (
                    int(str(value).split("@", 1)[0]) if str(value).split("@", 1)[0].isdigit() else 0,
                    str(value).casefold(),
                ),
            )
        )

        missing = []
        changed = []
        for asset in assets.values():
            destination = os.path.join(root, *asset.relative_path.split("/"))
            if not os.path.isfile(destination):
                missing.append(asset)
                continue
            old_row = old_by_id.get(asset.card_id, {})
            old_hash = old_row.get("evo_image_hash" if asset.kind == "evo" else "image_hash", "")
            if old_hash and old_hash != asset.image_hash:
                changed.append(asset)

        local_set_ids = set()
        for row in local_rows:
            set_id = str(row.get("card_set_id") or "")
            if set_id:
                local_set_ids.add(set_id)
                continue
            base_id = str(row.get("card_id") or "").split("@", 1)[0]
            if len(base_id) >= 3 and base_id[:3].isdigit():
                prefix = int(base_id[:3])
                if 100 <= prefix <= 199:
                    local_set_ids.add(str(10000 + prefix - 100))
        new_sets = tuple(
            sorted(
                ((key, value) for key, value in set_names.items() if key not in local_set_ids),
                key=lambda item: int(item[0]) if item[0].isdigit() else 0,
            )
        )
        existing_text = _csv_text(local_rows)
        merged_text = _csv_text(rows)
        plan = CardLibraryUpdatePlan(
            resource_root=root,
            rows=rows,
            assets=tuple(assets.values()),
            remote_card_count=len(remote_rows),
            local_row_count=len(local_rows),
            remote_set_names=dict(set_names),
            new_sets=new_sets,
            missing_assets=tuple(missing),
            changed_assets=tuple(changed),
            metadata_changed=existing_text != merged_text,
        )
        with _PLAN_CACHE_LOCK:
            _PLAN_CACHE[cache_key] = (time.monotonic(), plan)
        return plan

    def apply_plan(
        self,
        plan: CardLibraryUpdatePlan,
        *,
        download_images: bool = True,
        write_metadata: bool = True,
    ) -> Dict[str, int]:
        root = os.path.abspath(plan.resource_root)
        parent = os.path.dirname(root)
        os.makedirs(root, exist_ok=True)
        stage = tempfile.mkdtemp(prefix=".sv-card-update-stage-", dir=parent)
        backup = tempfile.mkdtemp(prefix=".sv-card-update-backup-", dir=parent)
        installed: list[str] = []
        backed_up: list[tuple[str, str]] = []
        try:
            downloads = plan.download_assets if download_images else ()
            for index, asset in enumerate(downloads, start=1):
                self._check_cancelled()
                self.progress(f"下载卡图 {index} / {len(downloads)}：{asset.card_id}")
                response = self._request(IMAGE_URL.format(image_hash=asset.image_hash))
                try:
                    image = Image.open(io.BytesIO(response.content))
                    image.load()
                except Exception as exc:
                    raise CardLibraryUpdateError(
                        f"卡图校验失败 {asset.card_id}: {exc}"
                    ) from exc
                stage_path = os.path.join(stage, *asset.relative_path.split("/"))
                os.makedirs(os.path.dirname(stage_path), exist_ok=True)
                image.save(stage_path, "WEBP", quality=90)

            for asset in downloads:
                source = os.path.join(stage, *asset.relative_path.split("/"))
                destination = os.path.join(root, *asset.relative_path.split("/"))
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                if os.path.exists(destination):
                    backup_path = os.path.join(backup, *asset.relative_path.split("/"))
                    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                    shutil.copy2(destination, backup_path)
                    backed_up.append((backup_path, destination))
                os.replace(source, destination)
                installed.append(destination)

            if write_metadata:
                write_text_atomic(
                    os.path.join(root, "SV_WB_Cards.csv"),
                    _csv_text(plan.rows),
                    encoding="utf-8",
                )
            remaining_plan = CardLibraryUpdatePlan(
                resource_root=plan.resource_root,
                rows=plan.rows,
                assets=plan.assets,
                remote_card_count=plan.remote_card_count,
                local_row_count=len(plan.rows) if write_metadata else plan.local_row_count,
                remote_set_names=plan.remote_set_names,
                new_sets=(),
                missing_assets=() if download_images else plan.missing_assets,
                changed_assets=() if download_images else plan.changed_assets,
                metadata_changed=bool(plan.metadata_changed and not write_metadata),
            )
            with _PLAN_CACHE_LOCK:
                _PLAN_CACHE[os.path.normcase(root)] = (
                    time.monotonic(),
                    remaining_plan,
                )
            return {
                "downloaded": len(downloads),
                "metadata_rows": len(plan.rows) if write_metadata else 0,
                "remote_cards": plan.remote_card_count,
            }
        except Exception:
            for destination in reversed(installed):
                try:
                    os.remove(destination)
                except OSError:
                    pass
            for backup_path, destination in backed_up:
                try:
                    os.makedirs(os.path.dirname(destination), exist_ok=True)
                    os.replace(backup_path, destination)
                except OSError:
                    pass
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)
            shutil.rmtree(backup, ignore_errors=True)
