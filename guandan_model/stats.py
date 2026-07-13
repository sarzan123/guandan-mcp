"""批量 JSONL 加载 + 属性频率统计。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from guandan_model.analyzer import Analyzer


class BatchFormatError(ValueError):
    """JSONL 文件存在但行解析失败。"""


class UnknownPropertyError(ValueError):
    """请求的属性不在 Analyzer 支持列表内。"""


# v0 支持的属性 → Analyzer 方法映射
_PROPERTY_METHOD: dict[str, str] = {
    "bomb_count": "bomb_count",
    "has_rocket": "has_rocket",
    "has_wild_card": "has_wild_card",
    "joker_count": "joker_count",
    "card_count": "card_count",
    "level_card_count": "level_card_count",
    "rank_histogram": "rank_histogram",
}


class Stats:
    """包装一批 DealResult,提供频率统计。"""

    def __init__(self, deals: list[dict]) -> None:
        self.deals: list[dict] = deals

    @classmethod
    def from_file(cls, path: str | Path) -> Stats:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"批次文件不存在: {path}")
        deals: list[dict] = []
        with path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    deals.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise BatchFormatError(f"第 {lineno} 行 JSON 解析失败: {e}") from e
        return cls(deals)

    def _validate_property(self, name: str) -> str:
        if name not in _PROPERTY_METHOD:
            raise UnknownPropertyError(f"未知属性 {name!r};支持: {sorted(_PROPERTY_METHOD.keys())}")
        return _PROPERTY_METHOD[name]

    def frequency(self, name: str) -> dict[Any, int]:
        """统计每个 deal × 每玩家的属性频次。

        返回 {value_as_str -> count} 或 {value_as_int -> count} 视属性而定。
        """
        method = self._validate_property(name)
        counter: Counter[Any] = Counter()
        for deal in self.deals:
            a = Analyzer(deal)
            values = getattr(a, method)()  # type: ignore[arg-type]
            for _pid, v in values.items():
                counter[v] += 1
        # 把 True/False 规范化为字符串键(bool 在 JSON 中不可序列化)
        normalized: dict[Any, int] = {}
        for k, c in counter.items():
            if isinstance(k, bool):
                normalized["True" if k else "False"] = c
            else:
                normalized[k] = c
        return normalized

    # 兼容别名:frequency_dist 与 frequency 行为完全一致
    frequency_dist = frequency
