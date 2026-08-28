"""读取并汇总供界面展示的持久化对战统计。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Tuple, Union

from src.config.paths import get_app_root


PathLike = Union[str, Path]


@dataclass(frozen=True)
class MatchRecord:
    """单场持久化对战的规范表示。"""

    occurred_at: datetime
    rounds: Optional[int]
    duration_seconds: Optional[float]
    run_id: str = ""
    source_file: str = ""
    result: str = "unknown"
    deck_slot: Optional[int] = None
    deck_file: str = ""
    deck_name: str = ""


@dataclass(frozen=True)
class MatchAggregate:
    """一组对战记录的汇总指标。"""

    battle_count: int = 0
    total_duration_seconds: float = 0.0
    duration_sample_count: int = 0
    total_rounds: int = 0
    rounds_sample_count: int = 0
    wins: int = 0
    losses: int = 0
    unknown_results: int = 0

    @property
    def average_duration_seconds(self) -> float:
        if self.duration_sample_count <= 0:
            return 0.0
        return self.total_duration_seconds / self.duration_sample_count

    @property
    def average_rounds(self) -> float:
        if self.rounds_sample_count <= 0:
            return 0.0
        return self.total_rounds / self.rounds_sample_count

    @property
    def decided_count(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        if self.decided_count <= 0:
            return 0.0
        return self.wins / self.decided_count


@dataclass(frozen=True)
class DailyBattleCount:
    day: date
    battle_count: int


@dataclass(frozen=True)
class DeckBattleSummary:
    deck_key: str
    deck_name: str
    deck_file: str
    slots: Tuple[int, ...]
    aggregate: MatchAggregate


@dataclass(frozen=True)
class StatisticsSnapshot:
    """统计页面消费的完整统计数据。"""

    records: Tuple[MatchRecord, ...]
    overall: MatchAggregate
    today: MatchAggregate
    current_run: MatchAggregate
    latest_run: MatchAggregate
    current_run_id: str
    latest_run_id: str
    daily_counts: Tuple[DailyBattleCount, ...]
    deck_summaries: Tuple[DeckBattleSummary, ...]
    files_loaded: int
    files_failed: int


_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
)

_DURATION_PART_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>\u5c0f\u65f6|\u65f6|hours?|hrs?|h|"
    r"\u5206\u949f|\u5206|minutes?|mins?|m|"
    r"\u79d2|seconds?|secs?|s)",
    re.IGNORECASE,
)


def parse_match_datetime(value: Any) -> Optional[datetime]:
    """将持久化对战日期解析为不带时区的本地时间。"""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        try:
            parsed = datetime.fromtimestamp(timestamp)
        except (OSError, OverflowError, ValueError):
            return None
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None

        iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(iso_text)
        except ValueError:
            parsed = None
            for date_format in _DATE_FORMATS:
                try:
                    parsed = datetime.strptime(text, date_format)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return None
    else:
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def parse_duration_seconds(value: Any) -> Optional[float]:
    """解析数值、时钟格式、中文或英文形式的时长。"""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        duration = float(value)
        return duration if duration >= 0 else None

    if not isinstance(value, str):
        return None

    text = value.strip().lower()
    if not text:
        return None

    try:
        duration = float(text)
        return duration if duration >= 0 else None
    except ValueError:
        pass

    if re.fullmatch(r"\d+(?::\d+){1,2}", text):
        parts = [float(part) for part in text.split(":")]
        if len(parts) == 2:
            minutes, seconds = parts
            return minutes * 60 + seconds
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds

    total = 0.0
    found = False
    for match in _DURATION_PART_RE.finditer(text):
        found = True
        amount = float(match.group("value"))
        unit = match.group("unit").lower()
        if unit in {"\u5c0f\u65f6", "\u65f6", "hour", "hours", "hr", "hrs", "h"}:
            total += amount * 3600
        elif unit in {
            "\u5206\u949f",
            "\u5206",
            "minute",
            "minutes",
            "min",
            "mins",
            "m",
        }:
            total += amount * 60
        else:
            total += amount
    return total if found else None


def parse_round_count(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        rounds = int(value)
    except (TypeError, ValueError):
        return None
    return rounds if rounds >= 0 else None


def parse_match_result(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"win", "won", "victory", "胜利", "勝利"}:
        return "win"
    if text in {"loss", "lose", "lost", "defeat", "失败", "失敗", "败北", "敗北"}:
        return "loss"
    return "unknown"


def parse_match_record(raw: Any, source_file: str = "") -> Optional[MatchRecord]:
    if not isinstance(raw, dict):
        return None

    occurred_at = parse_match_datetime(
        raw.get("date", raw.get("timestamp", raw.get("time")))
    )
    if occurred_at is None:
        return None

    deck_slot = parse_round_count(raw.get("deck_slot"))
    if deck_slot is not None and not 1 <= deck_slot <= 9:
        deck_slot = None

    return MatchRecord(
        occurred_at=occurred_at,
        rounds=parse_round_count(raw.get("rounds", raw.get("round_count"))),
        duration_seconds=parse_duration_seconds(
            raw.get("duration", raw.get("duration_seconds"))
        ),
        run_id=str(raw.get("run_id") or "").strip(),
        source_file=source_file,
        result=parse_match_result(raw.get("result", raw.get("outcome"))),
        deck_slot=deck_slot,
        deck_file=str(raw.get("deck_file") or "").strip(),
        deck_name=str(raw.get("deck_name") or "").strip(),
    )


def _extract_raw_records(payload: Any) -> Sequence[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return ()

    for key in ("match_history", "matches", "records", "data"):
        records = payload.get(key)
        if isinstance(records, list):
            return records

    if any(key in payload for key in ("date", "timestamp", "time")):
        return (payload,)
    return ()


def load_match_records(app_root: Optional[PathLike] = None) -> Tuple[MatchRecord, ...]:
    records, _, _ = _load_match_records_with_status(app_root)
    return records


def _load_match_records_with_status(
    app_root: Optional[PathLike] = None,
) -> Tuple[Tuple[MatchRecord, ...], int, int]:
    root = Path(app_root or get_app_root())
    roots = [root]
    if app_root is None:
        current_working_dir = Path.cwd()
        try:
            is_same_root = current_working_dir.resolve() == root.resolve()
        except OSError:
            is_same_root = current_working_dir.absolute() == root.absolute()
        if not is_same_root:
            roots.append(current_working_dir)

    records = []
    files_loaded = 0
    files_failed = 0
    seen_filenames = set()

    for candidate_root in roots:
        for stats_file in sorted(candidate_root.glob("round_stats_*.json")):
            if not stats_file.is_file():
                continue
            file_key = stats_file.name.casefold()
            if file_key in seen_filenames:
                continue
            seen_filenames.add(file_key)

            try:
                with stats_file.open("r", encoding="utf-8-sig") as file_handle:
                    payload = json.load(file_handle)
            except (OSError, UnicodeError, json.JSONDecodeError):
                files_failed += 1
                continue

            files_loaded += 1
            for raw_record in _extract_raw_records(payload):
                record = parse_match_record(raw_record, stats_file.name)
                if record is not None:
                    records.append(record)

    records.sort(key=lambda item: item.occurred_at)
    return tuple(records), files_loaded, files_failed


def aggregate_matches(records: Iterable[MatchRecord]) -> MatchAggregate:
    battle_count = 0
    total_duration = 0.0
    duration_samples = 0
    total_rounds = 0
    rounds_samples = 0
    wins = 0
    losses = 0
    unknown_results = 0

    for record in records:
        battle_count += 1
        if record.duration_seconds is not None:
            total_duration += record.duration_seconds
            duration_samples += 1
        if record.rounds is not None:
            total_rounds += record.rounds
            rounds_samples += 1
        if record.result == "win":
            wins += 1
        elif record.result == "loss":
            losses += 1
        else:
            unknown_results += 1

    return MatchAggregate(
        battle_count=battle_count,
        total_duration_seconds=total_duration,
        duration_sample_count=duration_samples,
        total_rounds=total_rounds,
        rounds_sample_count=rounds_samples,
        wins=wins,
        losses=losses,
        unknown_results=unknown_results,
    )


def build_daily_counts(
    records: Iterable[MatchRecord],
    days: int = 7,
    end_day: Optional[date] = None,
) -> Tuple[DailyBattleCount, ...]:
    """返回截至 ``end_day`` 的连续每日序列。"""

    days = max(1, int(days))
    end_day = end_day or date.today()
    first_day = end_day - timedelta(days=days - 1)
    counts = {first_day + timedelta(days=offset): 0 for offset in range(days)}

    for record in records:
        record_day = record.occurred_at.date()
        if record_day in counts:
            counts[record_day] += 1

    return tuple(DailyBattleCount(day, counts[day]) for day in sorted(counts))


def build_statistics_snapshot(
    records: Iterable[MatchRecord],
    current_run_id: Optional[str] = None,
    today: Optional[date] = None,
    files_loaded: int = 0,
    files_failed: int = 0,
) -> StatisticsSnapshot:
    normalized_records = tuple(sorted(records, key=lambda item: item.occurred_at))
    today = today or date.today()

    run_records = [record for record in normalized_records if record.run_id]
    latest_run_id = run_records[-1].run_id if run_records else ""
    requested_run_id = str(current_run_id or "").strip()
    selected_run_id = requested_run_id or latest_run_id

    if selected_run_id:
        current_records = [
            record for record in normalized_records if record.run_id == selected_run_id
        ]
    elif normalized_records:
        current_records = [normalized_records[-1]]
    else:
        current_records = []

    if latest_run_id:
        latest_records = [
            record for record in normalized_records if record.run_id == latest_run_id
        ]
    elif normalized_records:
        latest_records = [normalized_records[-1]]
    else:
        latest_records = []

    deck_groups: dict[str, list[MatchRecord]] = {}
    deck_metadata: dict[str, tuple[str, str, set[int]]] = {}
    for record in normalized_records:
        deck_file = str(record.deck_file or "").strip()
        deck_name = str(record.deck_name or "").strip()
        if deck_file:
            deck_key = "file:" + deck_file.casefold()
        elif deck_name:
            deck_key = "name:" + deck_name.casefold()
        else:
            deck_key = "__unassigned__"
            deck_name = "历史未标记卡组"
        deck_groups.setdefault(deck_key, []).append(record)
        previous_name, previous_file, slots = deck_metadata.get(
            deck_key,
            (deck_name, deck_file, set()),
        )
        if record.deck_slot is not None:
            slots.add(int(record.deck_slot))
        deck_metadata[deck_key] = (
            previous_name or deck_name,
            previous_file or deck_file,
            slots,
        )

    deck_summaries = []
    for deck_key, grouped_records in deck_groups.items():
        deck_name, deck_file, slots = deck_metadata[deck_key]
        deck_summaries.append(
            DeckBattleSummary(
                deck_key=deck_key,
                deck_name=deck_name or deck_file or "历史未标记卡组",
                deck_file=deck_file,
                slots=tuple(sorted(slots)),
                aggregate=aggregate_matches(grouped_records),
            )
        )
    deck_summaries.sort(
        key=lambda item: (
            item.deck_key == "__unassigned__",
            -item.aggregate.decided_count,
            item.deck_name.casefold(),
        )
    )

    return StatisticsSnapshot(
        records=normalized_records,
        overall=aggregate_matches(normalized_records),
        today=aggregate_matches(
            record for record in normalized_records if record.occurred_at.date() == today
        ),
        current_run=aggregate_matches(current_records),
        latest_run=aggregate_matches(latest_records),
        current_run_id=selected_run_id,
        latest_run_id=latest_run_id,
        daily_counts=build_daily_counts(normalized_records, days=7, end_day=today),
        deck_summaries=tuple(deck_summaries),
        files_loaded=max(0, int(files_loaded)),
        files_failed=max(0, int(files_failed)),
    )


def load_statistics(
    app_root: Optional[PathLike] = None,
    current_run_id: Optional[str] = None,
    today: Optional[date] = None,
) -> StatisticsSnapshot:
    records, files_loaded, files_failed = _load_match_records_with_status(app_root)
    return build_statistics_snapshot(
        records,
        current_run_id=current_run_id,
        today=today,
        files_loaded=files_loaded,
        files_failed=files_failed,
    )
