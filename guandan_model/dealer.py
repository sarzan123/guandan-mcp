"""发牌器:洗牌 / 发牌 / 结果封装。

掼蛋 v1.2:
- 108 张全部发给 4 家,每家 27 张,无底牌(v1.1 修复:真实掼蛋无底牌)
- 牌型组合不再包含三带一(`triple_with_single`),并保留 v1.1 的发牌规则
- SCHEMA_VERSION 1.2.0(破坏性变更:v1.1 删 bottom、v1.2 减 1 种牌型)
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

from guandan_model.cards import JOKER_CODES, RANKS, SUITS
from guandan_model.deck import Deck

# spec §3.5 与 §7.1: 对外暴露的 schema 版本常量(agent 检查)
# 1.2.0: 删 triple_with_single 牌型(从 15 种减到 14 种);保留 v1.1 的 4×27=108 + 无底牌
SCHEMA_VERSION = "1.2.0"

NUMBER_OF_PLAYERS = 4
HAND_SIZE = 27
LEVEL_RANK_DEFAULT = "2"
WILD_CARD_CODE = f"H{LEVEL_RANK_DEFAULT}"  # "H2"
VARIANT_DEFAULT = "two-deck-fengrenpei"


class DealInvariantError(RuntimeError):
    """发牌流程生成的结果违反已知不变量。"""


@dataclass(frozen=True)
class DealResult:
    seed: int
    variant: str
    level_rank: str
    hands: dict[str, list[str]]  # {"0": [...], "1": [...], ...} — 每家 27 张
    wild_card: str  # "H2"
    wild_card_owner: str | None  # 首位持 H2 的玩家 "0".."3";v1.1 永远在玩家手里
    total_cards: int = 108

    def __post_init__(self) -> None:
        # 由 hands 推导(避免外部传入与实际不一致)
        total = sum(len(h) for h in self.hands.values())
        object.__setattr__(self, "total_cards", total)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "seed": self.seed,
            "variant": self.variant,
            "level_rank": self.level_rank,
            "hands": {k: list(v) for k, v in self.hands.items()},
            "wild_card": self.wild_card,
            "wild_card_owner": self.wild_card_owner,
            "total_cards": self.total_cards,
        }


class Dealer:
    """静态工具类,封装随机洗牌与发牌流程。"""

    @staticmethod
    def shuffle(deck, *, seed: int | None = None, rng: random.Random | None = None) -> None:
        """原地 Fisher-Yates 洗牌。

        优先使用 rng;若 rng 为 None 则以 seed 实例化 random.Random。
        必须至少给出一个,否则抛错。
        """
        if rng is None and seed is None:
            raise ValueError("必须提供 seed 或 rng 之一")
        if rng is None:
            rng = random.Random(seed)
        # Fisher-Yates
        n = deck.size
        cards = deck.cards  # 引用 list 本身,直接 in-place
        for i in range(n - 1, 0, -1):
            j = rng.randint(0, i)
            cards[i], cards[j] = cards[j], cards[i]

    @classmethod
    def deal(cls, seed: int, *, variant: str = VARIANT_DEFAULT) -> DealResult:
        """按指定 seed 洗牌并发牌,返回 DealResult。

        v1.1: 4 玩家各 27 张 = 108(无底牌,wild_card_owner 永不为 "bottom")。
        v0 仅支持两副牌-逢人配(variant="two-deck-fengrenpei")。
        """
        if variant != VARIANT_DEFAULT:
            raise ValueError(f"当前仅支持 {VARIANT_DEFAULT},收到 {variant}")
        rng = random.Random(seed)
        deck = Deck()
        cls.shuffle(deck, rng=rng)
        cards = deck.cards

        # 4×27 平均分配(108 / 4 = 27)
        hands: dict[str, list[str]] = {str(i): [] for i in range(NUMBER_OF_PLAYERS)}
        for pid in range(NUMBER_OF_PLAYERS):
            hands[str(pid)] = cards[pid * HAND_SIZE : (pid + 1) * HAND_SIZE]

        # 不变量自检:总数 108,且多重集合等于规范两副牌
        total = sum(len(h) for h in hands.values())
        flat = [c for h in hands.values() for c in h]
        canonical: list[str] = []
        for _ in range(2):
            for s in SUITS:
                for rk in RANKS:
                    canonical.append(f"{s}{rk}")
            canonical.extend(JOKER_CODES)
        if total != 108 or Counter(flat) != Counter(canonical):
            raise DealInvariantError("发牌违反总数/多重集合不变量")

        # wild card 归属(取首个含 H2 的玩家;108 已全发,必在某个玩家手里)
        owner: str | None = None
        for pid in range(NUMBER_OF_PLAYERS):
            if WILD_CARD_CODE in hands[str(pid)]:
                owner = str(pid)
                break
        if owner is None:
            raise DealInvariantError("wild_card 在 108 张牌中找不到持有者(发牌不变量违反)")

        return DealResult(
            seed=seed,
            variant=variant,
            level_rank=LEVEL_RANK_DEFAULT,
            hands=hands,
            wild_card=WILD_CARD_CODE,
            wild_card_owner=owner,
        )
