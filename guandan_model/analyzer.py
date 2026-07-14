"""单 DealResult 属性查询。

每个属性支持两种粒度:
- per_player: 返回 dict[pid -> 值]
- per_hand : 返回 dict[pid -> 值] 但仅手牌(4 玩家,v1.1 无底牌)
- per_deal : 单值,跨全 deal 算(例如 wild_card_owner)
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from guandan_model.cards import JOKER_CODES, RANKS
from guandan_model.combinations import Combinations


class Analyzer:
    """Analyzer 接受 DealResult dict 或 DealResult 对象(自动 to_dict)。"""

    def __init__(self, deal: dict | object) -> None:
        if hasattr(deal, "to_dict"):
            self.deal: dict[str, Any] = deal.to_dict()  # type: ignore[attr-defined]
        elif isinstance(deal, dict):
            self.deal = deal
        else:
            raise TypeError("Analyzer 需要 dict 或 DealResult")
        self.level_rank: str = self.deal.get("level_rank", "2")
        self.hands: dict[str, list[str]] = self.deal["hands"]
        self.wild_card: str = self.deal.get("wild_card", f"H{self.level_rank}")
        self.wild_card_owner: str | None = self.deal.get("wild_card_owner")

    # ---------- per-player 属性 ----------

    def all_players(self) -> dict[str, dict[str, Any]]:
        """返回 {property_name -> {pid -> value}}。"""
        return {
            "bomb_count": self.bomb_count(),
            "has_rocket": self.has_rocket(),
            "has_wild_card": self.has_wild_card(),
            "joker_count": self.joker_count(),
            "card_count": self.card_count(),
            "level_card_count": self.level_card_count(),
            "rank_histogram": self.rank_histogram(),
            "combinations": self.combinations_count_all(),
        }

    def bomb_count(self) -> dict[str, int]:
        """每手牌炸弹总数(= bomb_4..8 + joker_bomb 之和)。

        v0.5 语义: 严格 掼蛋 炸弹 = 同 rank ≥4 张 且排除 level 牌,
        持有全部 4 张 joker 计 1 个 joker_bomb。
        v0 不计 joker_bomb,且使用「rank ≥2 同 rank」宽松定义 —— 本方法已升级到 v0.5 语义。
        """
        return {
            pid: Combinations(hand, self.level_rank).count_bombs()
            for pid, hand in self.hands.items()
        }

    def combinations_count_all(self) -> dict[str, dict[str, int]]:
        """每手牌的牌型计数({pid: {牌型: 个数}})。"""
        return {
            pid: Combinations(hand, self.level_rank).count_all() for pid, hand in self.hands.items()
        }

    def has_rocket(self) -> dict[str, bool]:
        return {pid: ("JOKER_B" in hand and "JOKER_S" in hand) for pid, hand in self.hands.items()}

    def has_wild_card(self) -> dict[str, bool]:
        return {pid: self.wild_card in hand for pid, hand in self.hands.items()}

    def joker_count(self) -> dict[str, int]:
        return {pid: sum(1 for c in hand if c in JOKER_CODES) for pid, hand in self.hands.items()}

    def card_count(self) -> dict[str, int]:
        return {pid: len(hand) for pid, hand in self.hands.items()}

    def level_card_count(self) -> dict[str, int]:
        return {
            pid: sum(1 for c in hand if not c.startswith("JOKER_") and c[1:] == self.level_rank)
            for pid, hand in self.hands.items()
        }

    def rank_histogram(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for pid, hand in self.hands.items():
            cnt = Counter(c[1:] for c in hand if c not in JOKER_CODES)
            hist = {r: 0 for r in RANKS}
            for rank, n in cnt.items():
                hist[rank] += n
            # JOKER 槽:仅在玩家持有 joker 时写入,保持 sum = 25 - jokers
            jn = sum(1 for c in hand if c in JOKER_CODES)
            if jn:
                hist["JOKER"] = 0  # 仅标记存在,数量走 joker_count()
            out[pid] = hist
        return out
