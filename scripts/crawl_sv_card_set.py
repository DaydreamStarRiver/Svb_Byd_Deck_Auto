#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动检查并增量更新 Shadowverse WB 官方卡牌库。

该入口与 GUI 共用 ``src.ui.card_library_update``：低频串行请求、429 退避、
图片完整解码后才安装，并在失败时回滚正式目录。``--card-set`` 用于确认目标
卡包已在官方清单出现；实际安装始终按远端与本地的完整差异执行，避免漏掉随新包
补充的跨卡包 token 或异画。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.ui.card_library_update import (  # noqa: E402
    CardLibraryUpdateError,
    OfficialCardLibraryClient,
)


DEFAULT_SAVE_DIR = os.path.join(PROJECT_ROOT, "quanka", "SV_WB_Cards")


def _parse_set_ids(value: str) -> List[str]:
    result = []
    for item in str(value or "").split(","):
        item = item.strip()
        if not item:
            continue
        if not item.isdigit():
            raise ValueError(f"卡包编号必须是数字: {item}")
        normalized = str(int(item))
        if normalized not in result:
            result.append(normalized)
    return result


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安全增量更新影之诗 WB 官方卡牌库")
    parser.add_argument(
        "--card-set",
        default="",
        help="确认官方已发布的目标卡包编号，逗号分隔；留空则自动检查全部差异",
    )
    parser.add_argument(
        "--save-dir",
        default=DEFAULT_SAVE_DIR,
        help=f"卡牌库目录（默认 {DEFAULT_SAVE_DIR}）",
    )
    parser.add_argument("--dict-only", action="store_true", help="只更新 CSV 元数据")
    parser.add_argument("--skip-dict", action="store_true", help="只补卡图，不更新 CSV")
    parser.add_argument("--dry-run", action="store_true", help="只显示差异，不写入文件")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.dict_only and args.skip_dict:
        print("--dict-only 与 --skip-dict 不能同时使用")
        return 2
    try:
        expected_sets = _parse_set_ids(args.card_set)
    except ValueError as exc:
        print(exc)
        return 2

    root = os.path.abspath(args.save_dir)
    print(f"卡牌库目录: {root}")
    client = OfficialCardLibraryClient(progress=lambda message: print(message))
    try:
        plan = client.fetch_plan(root)
        missing_sets = [
            set_id for set_id in expected_sets if set_id not in plan.remote_set_names
        ]
        if missing_sets:
            names = ", ".join(missing_sets)
            print(f"官方清单尚未出现目标卡包: {names}；已拒绝下载")
            return 3

        print("================ 差异预览 ================")
        print(f"官方卡牌/异画条目: {plan.remote_card_count}")
        print(f"合并后字典条目: {len(plan.rows)}")
        print(f"缺失卡图: {len(plan.missing_assets)}")
        print(f"内容变更卡图: {len(plan.changed_assets)}")
        if plan.new_sets:
            print("新增卡包: " + ", ".join(name for _sid, name in plan.new_sets))

        wants_images = not args.dict_only
        wants_metadata = not args.skip_dict
        relevant_updates = (
            bool(plan.download_assets) if wants_images else False
        ) or (plan.metadata_changed if wants_metadata else False)
        if args.dry_run:
            print("dry-run：未写入任何文件")
            return 0
        if not relevant_updates:
            print("本地卡牌库已是最新")
            return 0

        result = client.apply_plan(
            plan,
            download_images=wants_images,
            write_metadata=wants_metadata,
        )
        print(
            "更新完成：下载 {downloaded} 张卡图，字典 {metadata_rows} 条".format(
                **result
            )
        )
        return 0
    except CardLibraryUpdateError as exc:
        print(f"更新失败: {exc}")
        return 1
    except Exception as exc:
        print(f"更新异常: {exc}")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
