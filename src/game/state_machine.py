"""画面状态机。

将“检测画面、决策、执行动作”的主循环从 ``DeviceManager`` 中独立出来。
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, List

import cv2
import numpy as np


if TYPE_CHECKING:
    from src.device.device_state import DeviceState
    from src.game.game_manager import GameManager


class GameStateMachine:
    def process(self, device_state: "DeviceState", game_manager: "GameManager", skip_buttons: List[str]):
        """处理游戏主循环的一帧。"""

        out_of_match_keys = {
            "war",
            "mainPage",
            "MuMuPage",
            "LoginPage",
            "enterGame",
            "dailyCard",
            "rank",
            "missionCompleted",
            "rankUp",
            "groupUp",
            "backTitle",
            "gala_war",
            "gala_Ok",
            "gala_index",
            "gala_BackPark",
        }

        # 允许即时暂停或停止快速退出调用栈。
        device_state.check_interrupt()

        u2_device = device_state.get_u2_device()
        if u2_device is None:
            device_state.logger.warning("u2_device未连接，跳过本轮状态机处理")
            device_state.sleep(1)
            return

        # 获取截图
        screenshot = device_state.take_screenshot()
        if screenshot is None:
            device_state.sleep(2)
            return

        # 转换为OpenCV格式
        screenshot_np = np.array(screenshot)
        screenshot_cv = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)
        gray_screenshot = cv2.cvtColor(screenshot_cv, cv2.COLOR_BGR2GRAY)

        # 检查其他按钮
        templates = game_manager.template_manager.templates

        def _template_hit(template_key: str):
            info = templates.get(template_key)
            if not info:
                return False, None, 0.0
            location, score = game_manager.template_manager.match_template(
                gray_screenshot,
                info,
            )
            return (
                location is not None and score >= float(info["threshold"]),
                location,
                score,
            )

        # 真实结算页同时保留“对战”按钮。先联合判断结算结果，避免
        # war 分支先开启下一场后丢失上一场胜负。
        war_hit, _, _ = _template_hit("war")
        if war_hit and getattr(device_state, "in_match", False):
            settlement_result = None
            for settlement_key, result_value in (("win", "win"), ("result", "loss")):
                hit, _, _ = _template_hit(settlement_key)
                if not hit:
                    text_loc, text_score = game_manager.template_manager.match_text_key(
                        screenshot_cv,
                        settlement_key,
                    )
                    info = templates.get(settlement_key)
                    hit = bool(
                        text_loc is not None
                        and info is not None
                        and text_score >= float(info["threshold"])
                    )
                if hit:
                    settlement_result = result_value
                    break
            if settlement_result is not None:
                was_recordable = getattr(device_state, "match_start_time", None) is not None
                device_state.end_current_match(result=settlement_result)
                if was_recordable:
                    game_manager.deck_rotation.record_completed_match(settlement_result)

        # 页面文字只在所有常规模板均未命中时作为最后一个候选。
        template_candidates = list(templates.items()) + [
            ("__page_text_fallback__", None)
        ]

        for key, template_info in template_candidates:
            if key == "__page_text_fallback__":
                fallback = game_manager.template_manager.find_page_text_match(
                    screenshot_cv
                )
                if fallback is None:
                    continue
                key, max_loc, max_val = fallback
                template_info = templates.get(key)
                if not template_info:
                    continue
            else:
                if not template_info:
                    continue
                if key in {"win", "result"}:
                    # 结算模板只在 war 同帧命中时检测，避免战斗中每帧执行多尺度匹配。
                    continue
                max_loc, max_val = game_manager.template_manager.match_template(
                    gray_screenshot, template_info
                )
            if max_val >= template_info["threshold"] and max_loc is not None:
                matched_w = int(template_info.get("matched_w", template_info["w"]))
                matched_h = int(template_info.get("matched_h", template_info["h"]))

                # 记录阶段（仅在阶段变化时刷新“无新阶段”计时）。
                device_state.record_stage_detection(key)

                if key in {"end_round", "enemy_round"} and getattr(
                    device_state, "in_match", False
                ) and bool(getattr(game_manager.recognition, "uses_maa", False)):
                    try:
                        game_manager.observe_battle_state(screenshot)
                    except Exception as exc:
                        device_state.logger.debug("战斗数值识别失败，继续原流程: %s", exc)

                # WIN/RESULT 是结算标识，不是可点击按钮。
                if key in {"win", "result"}:
                    continue

                # 命中明显局外页面时，结束当前对战统计。
                if key in out_of_match_keys and getattr(device_state, "in_match", False):
                    device_state.end_current_match()

                # 达到总时长后：仅允许当前对战结束，不再开启下一场。
                if (
                    getattr(device_state, "stop_after_current_match", False)
                    and key in out_of_match_keys
                    and not getattr(device_state, "in_match", False)
                ):
                    stop_reason = str(
                        getattr(device_state, "stop_after_match_reason", "")
                        or "runtime_limit"
                    )
                    if stop_reason == "target_wins":
                        device_state.logger.info("目标胜场已达成，停止脚本且不再开始下一局")
                    else:
                        device_state.logger.info("达到脚本总时长上限，当前对战结束后停止脚本")
                    device_state.request_stop(reason=stop_reason)
                    break

                if key in skip_buttons:
                    continue
                if key == "LoginPage":
                    u2_device.click(
                        659 + random.randint(-10, 10), 338 + random.randint(-10, 10)
                    )
                    continue

                if key == "mainPage":
                    u2_device.click(
                        987 + random.randint(-10, 10), 447 + random.randint(-10, 10)
                    )
                    continue

                if key == "dailyCard":
                    u2_device.click(
                        640 + random.randint(-2, 2), 646 + random.randint(-2, 2)
                    )
                    continue

                if key != device_state.last_detected_button:
                    if key == "end_round" and device_state.in_match:
                        device_state.logger.debug(
                            f"已发现'结束回合'按钮 (当前回合: {device_state.current_round_count})"
                        )

                # 处理对战开始/结束逻辑
                if key == "war":
                    # 达到停止条件后，结算页仍可能保留“对战”按钮。这里再做
                    # 一次硬门禁，避免模板遍历顺序变化时误开下一局。
                    if (
                        getattr(device_state, "stop_after_current_match", False)
                        and not getattr(device_state, "in_match", False)
                    ):
                        stop_reason = str(
                            getattr(device_state, "stop_after_match_reason", "")
                            or "runtime_limit"
                        )
                        if stop_reason == "target_wins":
                            device_state.logger.info(
                                "目标胜场已达成，忽略对战按钮并停止脚本"
                            )
                        else:
                            device_state.logger.info(
                                "达到脚本总时长上限，忽略对战按钮并停止脚本"
                            )
                        device_state.request_stop(reason=stop_reason)
                        break

                    # 检测到"决斗"按钮，表示新对战开始
                    device_state.logger.debug(
                        f"检测到决斗按钮 - 当前in_match: {device_state.in_match}"
                    )
                    if game_manager.deck_rotation.has_pending:
                        if not game_manager.deck_rotation.perform_pending():
                            break

                    # war命中即视为新对战入口，重复触发由start_new_match内部防抖。
                    device_state.start_new_match()
                    # 计算中心点并点击
                    center_x = max_loc[0] + matched_w // 2
                    center_y = max_loc[1] + matched_h // 2
                    u2_device.click(
                        center_x + random.randint(-2, 2),
                        center_y + random.randint(-2, 2),
                    )
                    device_state.sleep(3)
                    device_state.logger.debug(
                        f"调用start_new_match后 - in_match: {device_state.in_match}"
                    )
                    # 同一张结算截图上还会存在其他局外模板；本帧到此结束，
                    # 避免刚开启的新局被后续模板立即记为“未判定”。
                    break

                # 处理庆典模式按钮
                if key in {"gala_war", "gala_Ok", "gala_index", "gala_BackPark"}:
                    # 检测到庆典模式按钮，计算中心点并点击
                    device_state.logger.debug(
                        f"检测到庆典模式按钮: {template_info['name']}"
                    )
                    # 计算中心点并点击
                    center_x = max_loc[0] + matched_w // 2
                    center_y = max_loc[1] + matched_h // 2
                    u2_device.click(
                        center_x + random.randint(-2, 2),
                        center_y + random.randint(-2, 2),
                    )
                    device_state.sleep(1)
                    continue

                if key == "decision":
                    # decision阶段若先于war被识别，兜底启动新对战。
                    if not getattr(device_state, "in_match", False):
                        device_state.start_new_match()
                    # 每局只执行一次换牌策略。
                    if not bool(getattr(device_state, "mulligan_done_this_match", False)):
                        config = device_state.config

                        strategy_setting = config.get("game", {}).get(
                            "card_replacement_strategy", "4费档次"
                        )

                        device_state.logger.info(
                            f"执行换牌策略: {strategy_setting} (canonical增强规则)"
                        )

                        # 等待换牌界面卡牌动画完成
                        device_state.sleep(0.4)

                        # Step3D 运行时只保留一条规范换牌路径。
                        success = game_manager.game_actions._detect_change_card_sift()

                        if not success:
                            device_state.logger.warning("换牌执行失败")

                        device_state.mulligan_done_this_match = True
                    else:
                        device_state.logger.info("本局换牌已执行，跳过重复换牌")

                    device_state.sleep(0.5)
                    center_x = max_loc[0] + matched_w // 2
                    center_y = max_loc[1] + matched_h // 2
                    u2_device.click(
                        center_x + random.randint(-2, 2),
                        center_y + random.randint(-2, 2),
                    )
                    # 避免decision界面残留导致下一轮再次执行换牌。
                    device_state.sleep(3)
                    break

                if key == "end_round":
                    device_state.logger.debug(
                        f"处理结束回合按钮 - in_match: {device_state.in_match}, 当前回合: {device_state.current_round_count}"
                    )

                    config = device_state.config
                    # 检查是否启用空过功能
                    enable_auto_pass = config.get("game", {}).get(
                        "enable_auto_pass", False
                    )
                    device_state.logger.debug(f"空过功能状态: {enable_auto_pass}")

                    if enable_auto_pass:
                        # 启用空过，直接点击结束回合按钮
                        device_state.logger.info("启用空过，直接结束回合")
                    else:
                        # 未启用空过，执行原有逻辑
                        # 根据是否有额外费用点决定进化/超进化执行回合
                        if device_state.extra_cost_available_this_match:
                            evolution_rounds = range(4, 25)  # 4到14，包含4和14
                        else:
                            evolution_rounds = range(5, 25)  # 5到14，包含5和14
                        if device_state.current_round_count in evolution_rounds:
                            game_manager.game_actions.perform_fullPlus_actions()
                        else:
                            game_manager.game_actions.perform_full_actions()

                    # 记录当前回合的费用使用情况（在回合结束时）
                    device_state.last_round_available_cost = (
                        device_state.current_round_count
                    )  # 当前回合的基础费用
                    # 如果有激活的额外费用点，加上额外费用（PP）
                    if (
                        device_state.extra_cost_active
                        and device_state.extra_cost_remaining_uses > 0
                    ):
                        device_state.last_round_available_cost += 1

                    # 记录实际使用的费用（从cost_history获取）
                    if hasattr(device_state, "cost_history") and device_state.cost_history:
                        device_state.last_round_cost_used = (
                            device_state.cost_history[-1]
                            if device_state.cost_history
                            else 0
                        )
                    else:
                        device_state.last_round_cost_used = 0

                    device_state.current_round_count += 1
                    device_state.has_clicked_plus_this_round = False

                    # 自动点击结束回合按钮
                    center_x = max_loc[0] + matched_w // 2
                    center_y = max_loc[1] + matched_h // 2
                    u2_device.click(
                        center_x + random.randint(-2, 2),
                        center_y + random.randint(-2, 2),
                    )
                    device_state.logger.info("结束回合")
                    if key != device_state.last_detected_button:
                        device_state.logger.debug(
                            f"检测到按钮并处理: {template_info['name']} "
                        )
                    device_state.last_detected_button = key
                    device_state.sleep(0.5)
                    break

                # 计算中心点并点击（除了结束回合按钮）
                center_x = max_loc[0] + matched_w // 2
                center_y = max_loc[1] + matched_h // 2
                u2_device.click(
                    center_x + random.randint(-2, 2),
                    center_y + random.randint(-2, 2),
                )

                if key != device_state.last_detected_button:
                    device_state.logger.debug(
                        f"检测到按钮并点击: {template_info['name']} "
                    )

                # 更新状态跟踪
                device_state.last_detected_button = key
                device_state.sleep(0.5)
                break
