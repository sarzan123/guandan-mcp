"""牌堆:两副标准牌合并,共 108 张。"""

from __future__ import annotations

from collections import Counter

from guandan_model.cards import JOKER_CODES, RANKS, SUITS


class DeckIntegrityError(ValueError):
    """牌堆元素数量违反 108 张不变量。"""


class Deck:
    """两副标准牌合并,每种 (suit, rank) 出现 2 次,joker 各 2 次。"""

    EXPECTED_SIZE = 108

    def __init__(self, cards: list[str] | None = None) -> None:
        if cards is None:
            cards = self._build_default()
        if len(cards) != self.EXPECTED_SIZE:
            raise DeckIntegrityError(f"牌堆应有 {self.EXPECTED_SIZE} 张,实为 {len(cards)}")
        self._validate_multiset(cards)
        self.cards: list[str] = list(cards)

    @classmethod
    def _validate_multiset(cls, cards: list[str]) -> None:
        """校验每种合法代号恰好出现 2 次。"""
        expected = Counter(cls._build_default())
        actual = Counter(cards)
        for code, want in expected.items():
            got = actual.get(code, 0)
            if got != want:
                raise DeckIntegrityError(f"牌 {code} 应有 {want} 张,实为 {got}")
        extras = set(actual) - set(expected)
        if extras:
            raise DeckIntegrityError(f"非法牌代号: {sorted(extras)}")

    @staticmethod
    def _build_default() -> list[str]:
        out: list[str] = []
        for _ in range(2):  # 双副
            for suit in SUITS:
                for rank in RANKS:
                    out.append(f"{suit}{rank}")
            out.extend(JOKER_CODES)
        return out

    @property
    def size(self) -> int:
        return len(self.cards)
