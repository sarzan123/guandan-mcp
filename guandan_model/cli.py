"""guandan-deal CLI 入口。

全局选项:
  --pretty : JSON 缩进格式化
  --chinese: hands/bottom 中英文版(HA -> 红心A)
退出码: 0 成功 / 2 参数错误 / 3 I/O 错误 / 4 数据错误 / 5 内部错误
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from guandan_model.analyzer import Analyzer  # noqa: E402
from guandan_model.cards import render
from guandan_model.dealer import Dealer
from guandan_model.stats import (  # noqa: E402
    BatchFormatError,
    Stats,
    UnknownPropertyError,
)

EXIT_OK = 0
EXIT_ARG = 2
EXIT_IO = 3
EXIT_DATA = 4
EXIT_INTERNAL = 5


def _add_global(p: argparse.ArgumentParser) -> None:
    p.add_argument("--pretty", action="store_true", help="JSON 缩进输出")
    p.add_argument("--chinese", action="store_true", help="中文牌面渲染")


def _emit(data: Any, pretty: bool, chinese: bool) -> None:
    if chinese:
        rendered_hands = {
            pid: [render(c, chinese=True) for c in hand] for pid, hand in data["hands"].items()
        }
        rendered_bottom = [render(c, chinese=True) for c in data["bottom"]]
        rendered_wild = render(data["wild_card"], chinese=True)
        data = {
            **data,
            "hands": rendered_hands,
            "bottom": rendered_bottom,
            "wild_card": rendered_wild,
        }
    indent = 2 if pretty else None
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=indent))
    if indent is not None:
        sys.stdout.write("\n")


def cmd_deal(args: argparse.Namespace) -> int:
    try:
        seed = int(args.seed)
    except (TypeError, ValueError):
        print(f"错误: --seed 必须为整数,收到 {args.seed!r}", file=sys.stderr)
        return EXIT_ARG
    try:
        result = Dealer.deal(seed=seed)
    except Exception as e:  # noqa: BLE001 - 兜底为内部错误
        print(f"错误: 发牌失败: {e}", file=sys.stderr)
        return EXIT_INTERNAL
    _emit(result.to_dict(), pretty=args.pretty, chinese=args.chinese)
    return EXIT_OK


def cmd_batch(args: argparse.Namespace) -> int:
    count = args.count
    if count > 100_000 and not args.force:
        print(f"错误: --count={count} 超过 100000 上限,需 --force", file=sys.stderr)
        return EXIT_ARG
    if count < 1:
        print("错误: --count 必须 ≥ 1", file=sys.stderr)
        return EXIT_ARG
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base_seed = args.base_seed
    with out_path.open("w", encoding="utf-8") as f:
        for i in range(count):
            r = Dealer.deal(seed=base_seed + i)
            f.write(json.dumps(r.to_dict(), ensure_ascii=False))
            f.write("\n")
    print(f"Wrote {count} deals to {out_path}", file=sys.stderr)
    return EXIT_OK


def _read_deal_input(target: str) -> dict:
    """优先按文件路径读取;若不存在,再按内联 JSON 解析。"""
    p = Path(target)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"错误: deal JSON 解析失败 - {e}", file=sys.stderr)
            sys.exit(EXIT_DATA)
    try:
        return json.loads(target)
    except json.JSONDecodeError as e:
        print(f"错误: 既不是文件,也不是合法 JSON - {e}", file=sys.stderr)
        sys.exit(EXIT_ARG)


def cmd_analyze(args: argparse.Namespace) -> int:
    deal = args.deal
    batch = args.batch
    query = args.query
    if (deal is None) == (batch is None):
        print("错误: --deal 与 --batch 必须二选一", file=sys.stderr)
        return EXIT_ARG
    if deal is not None:
        d = _read_deal_input(deal)
        try:
            a = Analyzer(d)
            result = a.all_players()
        except (TypeError, KeyError) as e:
            print(f"错误: deal payload 结构不合法: {e}", file=sys.stderr)
            return EXIT_DATA
        result["wild_card_owner"] = a.wild_card_owner
        result["wild_card"] = a.wild_card
        if not args.combinations:
            result.pop("combinations", None)  # 向后兼容:默认隐藏
        indent = 2 if args.pretty else None
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=indent))
        if indent is not None:
            sys.stdout.write("\n")
        return EXIT_OK
    # batch 模式
    if query is None:
        print("错误: --batch 必须配合 --query", file=sys.stderr)
        return EXIT_ARG
    try:
        stats = Stats.from_file(batch)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return EXIT_IO
    except BatchFormatError as e:
        print(str(e), file=sys.stderr)
        return EXIT_DATA
    try:
        freq = stats.frequency(query)
    except UnknownPropertyError as e:
        print(str(e), file=sys.stderr)
        return EXIT_ARG
    indent = 2 if args.pretty else None
    sys.stdout.write(json.dumps({query: freq}, ensure_ascii=False, indent=indent))
    if indent is not None:
        sys.stdout.write("\n")
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guandan-deal",
        description="掼蛋发牌模型 v0 CLI (deal/batch/analyze)",
    )
    _add_global(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    p_deal = sub.add_parser("deal", help="按 seed 发一副牌并输出 JSON")
    _add_global(p_deal)
    p_deal.add_argument("--seed", type=str, required=True, help="随机种子(整数)")
    p_deal.set_defaults(func=cmd_deal)

    p_batch = sub.add_parser("batch", help="按种子序列批量生成 JSONL")
    _add_global(p_batch)
    p_batch.add_argument("--count", type=int, default=3000)
    p_batch.add_argument("--output", default="data/batch.jsonl")
    p_batch.add_argument("--base-seed", type=int, default=0)
    p_batch.add_argument("--force", action="store_true")
    p_batch.set_defaults(func=cmd_batch)

    p_an = sub.add_parser("analyze", help="属性查询")
    _add_global(p_an)
    p_an.add_argument("--deal", help="DealResult JSON:文件路径或内联 JSON")
    p_an.add_argument("--batch", help="JSONL 批次文件")
    p_an.add_argument("--query", help="属性名")
    p_an.add_argument(
        "--combinations",
        action="store_true",
        help="在 --deal 模式输出牌型识别结果",
    )
    p_an.set_defaults(func=cmd_analyze)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
