import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.game.battle_runtime import BattleRuntimeState
from src.game.domain import FollowerRuntimeState


def _ours(uid: int, x: int, name: str, *, miss_count: int = 0, cfg_key: str = "") -> FollowerRuntimeState:
    return FollowerRuntimeState(
        side="ours",
        uid=uid,
        x=x,
        y=500,
        raw_name=name,
        base_name=name,
        source_cfg_key=cfg_key,
        miss_count=miss_count,
    )


def test_missed_state_not_selected_for_latest_play_origin() -> None:
    rt = BattleRuntimeState()
    rt.ours = [
        _ours(1, 900, "测试随从", miss_count=1),
        _ours(2, 700, "测试随从"),
    ]

    pos = rt.mark_latest_play_origin(card_name="测试随从", cfg_key="测试随从")

    assert pos == (700, 500)
    assert rt.ours[0].source_cfg_key == ""
    assert rt.ours[1].source_cfg_key == "测试随从"


def test_find_ours_pos_by_cfg_key_ignores_missed_state() -> None:
    rt = BattleRuntimeState()
    rt.ours = [
        _ours(1, 900, "测试随从", miss_count=1, cfg_key="测试随从"),
        _ours(2, 700, "测试随从", cfg_key="测试随从"),
    ]

    assert rt.find_ours_pos_by_cfg_key(cfg_key="测试随从", fallback_name="测试随从") == (700, 500)


def test_attack_pending_timeout_does_not_accept_raw_normal_downgrade() -> None:
    rt = BattleRuntimeState()
    st = _ours(1, 700, "测试随从")
    st.follower_type = "yellow"
    setattr(st, "_attack_spent_pending", 1)
    setattr(st, "_attack_spent_ts", 0.0)
    rt.ours = [st]

    rt.sync_ours([(700, 500, "normal", "测试随从")])

    assert rt.ours[0].follower_type == "yellow"
    assert int(getattr(rt.ours[0], "_attack_spent_pending", 0) or 0) == 0


def test_active_attack_pending_accepts_raw_normal_downgrade() -> None:
    rt = BattleRuntimeState()
    st = _ours(1, 700, "测试随从")
    st.follower_type = "yellow"
    rt.ours = [st]

    assert rt.mark_our_attack_spent((700, 500), fallback_name="测试随从") is True
    rt.sync_ours([(700, 500, "normal", "测试随从")])

    assert rt.ours[0].follower_type == "normal"


if __name__ == "__main__":
    for fn in (
        test_missed_state_not_selected_for_latest_play_origin,
        test_find_ours_pos_by_cfg_key_ignores_missed_state,
        test_attack_pending_timeout_does_not_accept_raw_normal_downgrade,
        test_active_attack_pending_accepts_raw_normal_downgrade,
    ):
        fn()
    print("smoke_runtime_state: ok")
