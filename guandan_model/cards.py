"""Card 数据层:常量、Hand 工具。NL 解析/渲染在 Task 3/4。"""

from __future__ import annotations

import re
from dataclasses import dataclass

SUITS: tuple[str, ...] = ("S", "H", "D", "C")
RANKS: tuple[str, ...] = (
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "T",
    "J",
    "Q",
    "K",
    "A",
)
JOKER_CODES: tuple[str, ...] = ("JOKER_S", "JOKER_B")

# rank 与数值的映射,用于 Hand.sorted 与后续炸弹判定
RANK_VALUE: dict[str, int] = {r: i for i, r in enumerate(RANKS)}
SUIT_VALUE: dict[str, int] = {s: i for i, s in enumerate(SUITS)}


def _card_sort_key(code: str) -> tuple[int, int, int]:
    """joker 单独排到最后;非 joker 按 (rank_value, suit_value) 升序。"""
    if code in JOKER_CODES:
        # 大王 > 小王
        return (1, JOKER_CODES.index(code), 0)
    rank = code[1:]
    suit = code[0]
    return (0, RANK_VALUE[rank], SUIT_VALUE[suit])


def build_standard_deck() -> list[str]:
    """返回一套标准 54 张牌(52 + 2 jokers),顺序固定。"""
    deck: list[str] = []
    for suit in SUITS:
        for rank in RANKS:
            deck.append(f"{suit}{rank}")
    deck.extend(JOKER_CODES)
    return deck


STANDARD_DECK: list[str] = build_standard_deck()


@dataclass(frozen=True)
class Hand:
    cards: tuple[str, ...]

    def __post_init__(self) -> None:
        # Frozen dataclass requires object.__setattr__ to bypass frozen check
        object.__setattr__(self, "cards", tuple(self.cards))

    def sorted(self) -> list[str]:
        return sorted(self.cards, key=_card_sort_key)

    def filter_rank(self, rank: str) -> list[str]:
        return [c for c in self.cards if not c.startswith("JOKER_") and c[1:] == rank]

    def count_rank(self, rank: str) -> int:
        return len(self.filter_rank(rank))

    def count_joker(self) -> int:
        return sum(1 for c in self.cards if c in JOKER_CODES)


class CardParseError(ValueError):
    """NL 输入无法识别为合法牌。"""


# 常见同义:红桃(红心)、草花(梅花)、块(方片)在 v0 不收,见 plan §6.1。
# 后续若要扩展,在此处追加即可。
_SUIT_ALIASES: dict[str, str] = {
    "红心": "H",
    "心": "H",
    "黑桃": "S",
    "桃": "S",
    "方片": "D",
    "方": "D",
    "梅花": "C",
    "梅": "C",
    "花": "C",
}

_RANK_ALIASES: dict[str, str] = {
    "a": "A",
    "1": "A",
    "一": "A",
    "t": "T",
    "10": "T",
    "十": "T",
    "j": "J",
    "q": "Q",
    "k": "K",
    "2": "2",
    "3": "3",
    "4": "4",
    "5": "5",
    "6": "6",
    "7": "7",
    "8": "8",
    "9": "9",
}

_JOKER_ALIASES: dict[str, str] = {
    "大王": "JOKER_B",
    "大鬼": "JOKER_B",
    "小王": "JOKER_S",
    "小鬼": "JOKER_S",
}


def parse(text: str) -> str:
    """将自然语言牌描述解析为内部代号。

    接受形式:「<suit 名><rank 名>」(可含空格),或完整的「大王」「小王」等。
    大小写不敏感,多余空白被忽略。
    """
    if not isinstance(text, str):
        raise CardParseError(f"输入必须是字符串,收到 {type(text).__name__}")
    norm = text.strip().lower().replace(" ", "")
    if not norm:
        raise CardParseError("输入为空")
    # joker 全匹配(优先)
    if norm in _JOKER_ALIASES:
        return _JOKER_ALIASES[norm]
    # 匹配 「<suit 前缀><rank 后缀>」,suit 至少 1 字符,rank 在末尾
    m = re.fullmatch(r"([一-龥]+)([a-z0-9一-龥]+)", norm)
    if not m:
        raise CardParseError(f"无法解析: {text!r}")
    suit_part, rank_part = m.group(1), m.group(2)
    suit = _SUIT_ALIASES.get(suit_part)
    if suit is None:
        raise CardParseError(f"未知花色: {suit_part!r}")
    rank = _RANK_ALIASES.get(rank_part)
    if rank is None:
        raise CardParseError(f"未知牌值: {rank_part!r}")
    return f"{suit}{rank}"


class CardRenderError(ValueError):
    """给 render 的内部代号无法识别。"""


_SUIT_TO_CN: dict[str, str] = {
    "S": "黑桃",
    "H": "红心",
    "D": "方片",
    "C": "梅花",
}

_RANK_TO_CN: dict[str, str] = {
    "T": "10",
}

_JOKER_TO_CN: dict[str, str] = {"JOKER_B": "大王", "JOKER_S": "小王"}


def render(code: str, *, chinese: bool = False) -> str:
    """将内部代号渲染为字符串。

    chinese=False 时输出 ASCII 紧凑形式(可逆);
    chinese=True 时输出中文习惯形式(例如 "红心A" / "黑桃10" / "大王")。
    """
    if not isinstance(code, str) or not code:
        raise CardRenderError(f"非法代号: {code!r}")
    if code in JOKER_CODES:
        return _JOKER_TO_CN[code] if chinese else code
    if len(code) != 2 or code[0] not in SUITS or code[1] not in RANKS:
        raise CardRenderError(f"无法识别: {code!r}")
    suit, rank = code[0], code[1]
    if not chinese:
        return code
    return f"{_SUIT_TO_CN[suit]}{_RANK_TO_CN.get(rank, rank)}"
