"""掼蛋牌型识别。

v1.2:
- 去掉不存在的「三带一」(triple_with_single):掼蛋只有三张或三带二。
  钢板不能带翅膀,三带只能带 1 个对子。
- 不做 wild substitution:虽然红心级牌(H2)按游戏规则是百搭,实际牌型计数时
  仍按其本身 rank 处理(不模拟 wild 指派)。出牌阶段的百搭逻辑不在本模块范围。
- "count" 是「最大 disjoint 数」(例:AAAA = 4 single + 2 pair + 1 bomb_4)
- task 1:single / pair / triple / bomb_4..8
- task 2:triple_with_pair / straight / tube / plate
- task 3:straight_flush / joker_bomb
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from guandan_model.cards import JOKER_CODES, RANKS, SUITS

# 掼蛋标准:可参与顺子/连对/钢板的 rank 集合(不含 2 与 joker)
STRAIGHT_RANKS: tuple[str, ...] = (
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

# v1.2 支持的牌型(14 种):已删三带一(v0.5 错误加入);钢板不带翅膀;三带只能带 1 对
SUPPORTED_TYPES: tuple[str, ...] = (
    "single",
    "pair",
    "triple",
    "bomb_4",
    "bomb_5",
    "bomb_6",
    "bomb_7",
    "bomb_8",
    "triple_with_pair",
    "straight",
    "tube",
    "plate",
    "straight_flush",
    "joker_bomb",
)


@dataclass(frozen=True)
class Combination:
    """一个具体牌型实例。

    length:
      - 绝大多数类型 = 该牌型所用牌张数(single=1, pair=2, triple=3, bomb_n=n)
      - straight / tube / plate = 连续 rank 的「长度」,不是牌张数
        (straight: 1 张/rank; tube: 2 张/rank; plate: 3 张/rank)
      - triple_with_pair=5
    """

    type: str
    primary_rank: str | None
    cards: tuple[str, ...]
    length: int


class Combinations:
    """手牌 → 牌型识别。"""

    def __init__(
        self,
        hand: list[str] | tuple[str, ...],
        level_rank: str = "2",
    ) -> None:
        self.hand: tuple[str, ...] = tuple(hand)
        self.level_rank: str = level_rank
        # rank 直方图:仅非 joker 牌
        self._cnt: Counter[str] = Counter(c[1:] for c in self.hand if c not in JOKER_CODES)
        self._jokers: int = sum(1 for c in self.hand if c in JOKER_CODES)

    # ---------- 公共 API ----------

    def count(self, type_name: str) -> int:
        """单牌型计数。"""
        if type_name not in SUPPORTED_TYPES:
            raise ValueError(f"v1.2 不支持牌型 {type_name!r};支持: {SUPPORTED_TYPES}")
        return len(self.find(type_name))

    def count_all(self) -> dict[str, int]:
        """返回 {牌型名: 个数}。"""
        return {t: self.count(t) for t in SUPPORTED_TYPES}

    def count_bombs(self) -> int:
        """炸弹总数(= bomb_4 + bomb_5 + bomb_6 + bomb_7 + bomb_8 + joker_bomb 之和)。

        joker_bomb(天王炸)是 v0.5 task 3 新增的最高级炸弹,持有全部 4 张 joker 即计 1。
        """
        return sum(self.count(f"bomb_{n}") for n in range(4, 9)) + self.count("joker_bomb")

    def find(self, type_name: str) -> list[Combination]:
        """列举指定牌型的所有 disjoint 实例。

        注意:triple_with_pair 返回笛卡尔积(triple × pair),实例数可能较大。
        """
        if type_name == "single":
            return self._find_singles()
        if type_name == "pair":
            return self._find_pairs()
        if type_name == "triple":
            return self._find_triples()
        if type_name in ("bomb_4", "bomb_5", "bomb_6", "bomb_7", "bomb_8"):
            n = int(type_name.split("_")[1])
            return self._find_bombs(n)
        if type_name == "triple_with_pair":
            return self._find_triple_with_pair()
        if type_name == "straight":
            return self._find_straight()
        if type_name == "tube":
            return self._find_tube()
        if type_name == "plate":
            return self._find_plate()
        if type_name == "straight_flush":
            return self._find_straight_flush()
        if type_name == "joker_bomb":
            return self._find_joker_bomb()
        raise ValueError(f"v1.2 不支持牌型 {type_name!r}")

    def find_all(self) -> list[Combination]:
        """列举所有 supported 牌型(disjoint,按声明顺序)。"""
        out: list[Combination] = []
        for t in SUPPORTED_TYPES:
            out.extend(self.find(t))
        return out

    # ---------- 单张 ----------

    def _find_singles(self) -> list[Combination]:
        """每张牌 = 1 个 single,包括 joker。"""
        out: list[Combination] = []
        for c in self.hand:
            if c in JOKER_CODES:
                out.append(Combination(type="single", primary_rank=None, cards=(c,), length=1))
            else:
                out.append(Combination(type="single", primary_rank=c[1:], cards=(c,), length=1))
        return out

    # ---------- 对子/三张(排除 level rank)----------

    def _find_pairs(self) -> list[Combination]:
        """每 2 张同 rank ≠ level = 1 pair。disjoint。"""
        out: list[Combination] = []
        # pair 与 triple 不互相排斥:每种类型各自取 max disjoint。
        # 例:5 张 A → pair=2 (4 张) + triple=1 (3 张),同一 rank 被多种类型共同使用。
        for rank in RANKS:
            if rank == self.level_rank:
                continue
            n = self._cnt.get(rank, 0)
            for _ in range(n // 2):
                cards = self._pick_cards_of_rank(rank, 2)
                out.append(Combination(type="pair", primary_rank=rank, cards=cards, length=2))
        return out

    def _find_triples(self) -> list[Combination]:
        """每 3 张同 rank ≠ level = 1 triple。disjoint。"""
        out: list[Combination] = []
        for rank in RANKS:
            if rank == self.level_rank:
                continue
            n = self._cnt.get(rank, 0)
            for _ in range(n // 3):
                cards = self._pick_cards_of_rank(rank, 3)
                out.append(Combination(type="triple", primary_rank=rank, cards=cards, length=3))
        return out

    # ---------- 炸弹 4-8 张(排除 level rank)----------

    def _find_bombs(self, n: int) -> list[Combination]:
        """n 张同 rank ≠ level = 1 bomb_n。仅当 cnt[r] == n 时计(避免与 bomb_{n+1} 重叠)。"""
        out: list[Combination] = []
        for rank in RANKS:
            if rank == self.level_rank:
                continue
            if self._cnt.get(rank, 0) == n:
                cards = self._pick_cards_of_rank(rank, n)
                out.append(Combination(type=f"bomb_{n}", primary_rank=rank, cards=cards, length=n))
        return out

    # ---------- 三带对 ----------

    def _find_triple_with_pair(self) -> list[Combination]:
        """triple × pair (pair rank ≠ triple rank) 的笛卡尔积。count = num_triple × num_pair。

        pair 与 triple 必须不同 rank,否则会与 triple 共享物理牌
        (rank 最多 4 张,同 rank 同时 1 triple + 1 pair 需要 5 张)。
        """
        triples = self._find_triples()
        if not triples:
            return []
        pairs = self._find_pairs()
        if not pairs:
            return []
        out: list[Combination] = []
        for t in triples:
            for p in pairs:
                if p.primary_rank == t.primary_rank:
                    continue
                out.append(
                    Combination(
                        type="triple_with_pair",
                        primary_rank=t.primary_rank,
                        cards=t.cards + p.cards,
                        length=5,
                    )
                )
        return out

    # ---------- 顺子 / 连对 / 钢板 ----------

    def _eligible_ranks(self) -> list[str]:
        """straight/tube/plate 可参与的 rank 列表(STRAIGHT_RANKS 去掉 level)。"""
        return [r for r in STRAIGHT_RANKS if r != self.level_rank]

    def _consecutive_runs(
        self,
        min_count: int,
        counter: Counter[str] | None = None,
        ranks: list[str] | None = None,
    ) -> list[tuple[int, int]]:
        """扫描给定 rank 序列,找出所有「连续段」,返回 [(start_idx, end_idx_exclusive), ...]。

        start_idx/end_idx 是传入 ranks 中的下标。连续段内每个 rank 的 cnt ≥ min_count。

        参数:
            min_count: 每段每个 rank 至少几张牌(1=single,2=tube,3=plate,...)
            counter: 自定义 rank 直方图;None = 默认 self._cnt(全手牌)。
                    straight_flush 等 per-suit 扫描时传 suit-specific counter。
            ranks: 待扫描的 rank 序列;None = 默认 _eligible_ranks()(STRAIGHT_RANKS 去掉 level)。
                   straight_flush 显式传 STRAIGHT_RANKS(不排除 level_rank)。
        """
        if counter is None:
            counter = self._cnt
        if ranks is None:
            ranks = self._eligible_ranks()
        runs: list[tuple[int, int]] = []
        start: int | None = None
        for i, r in enumerate(ranks):
            if counter.get(r, 0) >= min_count:
                if start is None:
                    start = i
            else:
                if start is not None:
                    runs.append((start, i))
                    start = None
        if start is not None:
            runs.append((start, len(ranks)))
        return runs

    def _find_straight(self) -> list[Combination]:
        """5+ 连续 rank = 1 个 straight。

        规则:
          - 一般情况:5+ 连续 rank(都在 STRAIGHT_RANKS \\ level 中,且不跨 A)。
          - 特殊: A-2-3-4-5 是合法最小顺子(包含 2),其它含 2 的"顺子"非法。
          - 不重复计数更长/更短的子集:每段连续区间(长度 ≥ 5)计 1 个。
        """
        ranks = self._eligible_ranks()
        out: list[Combination] = []

        for start, end in self._consecutive_runs(min_count=1):
            length = end - start
            if length < 5:
                continue
            cards: list[str] = []
            for i in range(start, end):
                cards.append(self._pick_cards_of_rank(ranks[i], 1)[0])
            out.append(
                Combination(
                    type="straight",
                    primary_rank=ranks[start],
                    cards=tuple(cards),
                    length=length,
                )
            )

        # 特殊: A-2-3-4-5(包含 2 的唯一合法顺子)。A 在 STRAIGHT_RANKS 中,2 不在;
        # 所以一般扫描不会跨越。需要单独检测。
        # 条件:A/2/3/4/5 各至少 1 张(与 level_rank 无关——straight 排除 2 是牌型机制,
        # 而 A2345 是"含 2 的特例";level_rank 只影响 pair/triple/bomb)。
        if all(self._cnt.get(r, 0) >= 1 for r in ("A", "2", "3", "4", "5")):
            cards = tuple(self._pick_cards_of_rank(r, 1)[0] for r in ("A", "2", "3", "4", "5"))
            out.append(
                Combination(
                    type="straight",
                    primary_rank="A",
                    cards=cards,
                    length=5,
                )
            )
        return out

    def _find_tube(self) -> list[Combination]:
        """3+ 连续对(rank ∈ STRAIGHT_RANKS \\ level,每个 rank 至少 2 张)= 1 个 tube。

        每段连续区间(长度 ≥ 3,每个 rank cnt≥2)计 1 个。
        """
        ranks = self._eligible_ranks()
        out: list[Combination] = []

        for start, end in self._consecutive_runs(min_count=2):
            length = end - start
            if length < 3:
                continue
            cards: list[str] = []
            for i in range(start, end):
                cards.extend(self._pick_cards_of_rank(ranks[i], 2))
            out.append(
                Combination(
                    type="tube",
                    primary_rank=ranks[start],
                    cards=tuple(cards),
                    length=length,
                )
            )
        return out

    def _find_plate(self) -> list[Combination]:
        """2+ 连续 triple(rank ∈ STRAIGHT_RANKS \\ level,每个 rank 至少 3 张)= 1 个 plate。

        每段连续区间(长度 ≥ 2,每个 rank cnt≥3)计 1 个。
        """
        ranks = self._eligible_ranks()
        out: list[Combination] = []

        for start, end in self._consecutive_runs(min_count=3):
            length = end - start
            if length < 2:
                continue
            cards: list[str] = []
            for i in range(start, end):
                cards.extend(self._pick_cards_of_rank(ranks[i], 3))
            out.append(
                Combination(
                    type="plate",
                    primary_rank=ranks[start],
                    cards=tuple(cards),
                    length=length,
                )
            )
        return out

    def _pick_cards_of_rank(self, rank: str, n: int) -> tuple[str, ...]:
        """取手牌中前 n 张同 rank 的牌(joker 不参与)。"""
        return tuple(c for c in self.hand if c[1:] == rank)[:n]

    # ---------- 同花顺 (Task 3) ----------

    def _find_straight_flush(self) -> list[Combination]:
        """5+ 同花色且 rank 连续 = 1 个 straight_flush。

        规则:
          - suit 固定(每个 suit 独立扫描)
          - rank ∈ STRAIGHT_RANKS(3..A),不含 2 不含 joker
          - **不排除 level_rank**(与 straight 不同:level rank 仍可参与同花顺)
          - 不实现 A2345 特例(A2345 含 2,被 STRAIGHT_RANKS 自然排除)
          - 每段连续区间(长度 ≥ 5)计 1 个,不重数 5 张子集

        返回:每个 suit 最多 1 个 straight_flush(per-suit, disjoint)。
        """
        # 单次扫描构建 per-suit 的 rank→card 映射,避免在内层循环线性扫描手牌
        suit_to_rank_card: dict[str, dict[str, str]] = {s: {} for s in SUITS}
        for c in self.hand:
            if c in JOKER_CODES:
                continue
            suit, rank = c[0], c[1:]
            if rank in suit_to_rank_card[suit]:
                continue  # 每 rank 每 suit 取第一张即可
            suit_to_rank_card[suit][rank] = c

        out: list[Combination] = []
        for suit in SUITS:
            suit_cnt = Counter(suit_to_rank_card[suit].keys())
            for s_idx, e_idx in self._consecutive_runs(
                min_count=1, counter=suit_cnt, ranks=STRAIGHT_RANKS
            ):
                length = e_idx - s_idx
                if length < 5:
                    continue
                cards = tuple(
                    suit_to_rank_card[suit][STRAIGHT_RANKS[i]] for i in range(s_idx, e_idx)
                )
                out.append(
                    Combination(
                        type="straight_flush",
                        primary_rank=STRAIGHT_RANKS[s_idx],
                        cards=cards,
                        length=length,
                    )
                )
        return out

    # ---------- 天王炸 (Task 3) ----------

    def _find_joker_bomb(self) -> list[Combination]:
        """同时持有 4 张大小王(2 black + 2 red) = 1 个 joker_bomb(天王炸)。

        规则:
          - 2 副牌共 4 张 joker(2 张 JOKER_S + 2 张 JOKER_B)
          - 必须 4 张齐全 = 1 个;否则 0
          - **不依赖 level_rank**
          - 与 bomb_4..8 不重叠(jokers 不参与 bomb 判定)
        """
        if self._jokers != 4:
            return []
        cards = tuple(c for c in self.hand if c in JOKER_CODES)
        return [
            Combination(
                type="joker_bomb",
                primary_rank=None,
                cards=cards,
                length=4,
            )
        ]
