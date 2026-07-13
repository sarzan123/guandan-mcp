"""掼蛋发牌模型 v0.5 — MCP Server。

通过 Gradio 部署到 Hugging Face Spaces,自动暴露为 MCP tools。
朋友的 Claude Code / OpenCode / Hermes Agent 等智能体可调用本服务回答掼蛋问题。

设计原则:
- 每个函数 = 一个 MCP tool(中文 docstring = 工具描述,供智能体理解)
- 主要功能用 gr.Interface 同时提供 Web UI
- 辅助功能用 gr.api 提供纯逻辑(无 UI)
- 牌型中文名 ↔ 英文 key 映射统一从 SUPPORTED_TYPES 派生
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import gradio as gr

from guandan_model.analyzer import Analyzer
from guandan_model.cards import render
from guandan_model.combinations import SUPPORTED_TYPES, Combinations
from guandan_model.dealer import Dealer
from guandan_model.stats import Stats

# HF ZeroGPU Spaces 启动时要求至少一个 @spaces.GPU 装饰函数。
# 此桩函数仅用于通过 ZeroGPU 健康检查,不被任何 MCP / UI 路径调用。
try:
    import spaces

    @spaces.GPU(duration=1)
    def _zero_gpu_healthcheck() -> str:
        """ZeroGPU 启动健康检查占位 — 不被任何 MCP 路径调用。"""
        return "ok"
except ImportError:
    pass  # 非 ZeroGPU 环境(CPU / 纯 Docker)不需要此装饰器

# ---------- 15 牌型中英文映射 ----------

CN_NAME: dict[str, str] = {
    "single": "单张",
    "pair": "对子",
    "triple": "三张",
    "bomb_4": "4张炸",
    "bomb_5": "5张炸",
    "bomb_6": "6张炸",
    "bomb_7": "7张炸",
    "bomb_8": "8张炸",
    "triple_with_single": "三带一",
    "triple_with_pair": "三带二",
    "straight": "顺子",
    "tube": "连对",
    "plate": "钢板",
    "straight_flush": "同花顺",
    "joker_bomb": "天王炸",
}
EN_TO_CN: dict[str, str] = {k: CN_NAME.get(k, k) for k in SUPPORTED_TYPES}
CN_TO_EN: dict[str, str] = {v: k for k, v in CN_NAME.items()}

# ---------- 牌型名校验 ----------

VALID_TYPE_NAMES = (
    "15 种牌型(中文): "
    + ", ".join(CN_NAME[k] for k in SUPPORTED_TYPES)
    + " | (英文): "
    + ", ".join(SUPPORTED_TYPES)
)
VALID_ATTRIBUTES = (
    "bomb_count",
    "has_rocket",
    "has_wild_card",
    "joker_count",
    "card_count",
    "level_card_count",
    "rank_histogram",
)


# ---------- 内置 3000 局样本 ----------

BUILTIN_BATCH_PATH = Path(__file__).parent / "data" / "batch_3000.jsonl"
BUILTIN_BATCH_AVAILABLE = BUILTIN_BATCH_PATH.exists()
DEFAULT_DEAL_JSON = json.dumps(
    {
        "seed": 0,
        "variant": "two-deck-fengrenpei",
        "level_rank": "2",
        "hands": {"0": ["HA", "SA", "DA", "CA"], "1": [], "2": [], "3": []},
        "bottom": ["H2", "DQ", "SJ", "C9", "H9", "D5", "S5", "CT"],
        "wild_card": "H2",
        "wild_card_owner": "0",
        "total_cards": 12,
    },
    ensure_ascii=False,
)


# ---------- 工具函数实现 ----------


def deal_hand(seed: int, level_rank: str = "2") -> dict:
    """按种子发一手牌(4 玩家 + 8 底牌),返回完整 DealResult。

    Args:
        seed: 整数种子(可重现)。常用值: 0, 1, 42, 100。
        level_rank: 级牌等级,决定哪些牌是级牌(默认 "2",目前 v0 Dealer
            固定为 "2",非 "2" 会被忽略)。

    Returns:
        dict: 包含 schema_version, seed, variant, level_rank, hands (4 玩家),
              bottom (8 底牌), wild_card (红心配级牌), wild_card_owner (持有者),
              total_cards (108)。
    """
    deal = Dealer.deal(seed=int(seed)).to_dict()
    if level_rank != deal["level_rank"]:
        deal["requested_level_rank"] = level_rank
    return deal


def analyze_hand(hand_text: str, level_rank: str = "2") -> dict:
    """分析一手牌(空格分隔的牌代号),返回 15 种牌型识别结果。

    牌代号格式: 花色字母(S/H/D/C) + 数字(2-9/T/J/Q/K/A),
    大小王为 JOKER_S(小王) / JOKER_B(大王)。
    例: "HA SA DA CA" = 4 张 A;"JOKER_S JOKER_B" = 大小王一对。

    Args:
        hand_text: 手牌(空格分隔),如 "HA SA DA CA H3 H4 H5"
        level_rank: 级牌等级(默认 "2")。级牌不计入炸弹和三带。

    Returns:
        dict: 包含
            - hand: 解析后的牌列表
            - count_all: 15 种牌型的实例数(中文名)
            - count_bombs: 炸弹总数(bomb_4..8 + 天王炸)
            - has_rocket: 是否同时持有大小王
            - hand_size: 牌张数
    """
    cards = hand_text.strip().split()
    c = Combinations(cards, level_rank)
    count_all_en = c.count_all()
    count_all_cn = {EN_TO_CN.get(k, k): v for k, v in count_all_en.items()}
    return {
        "hand": cards,
        "level_rank": level_rank,
        "hand_size": len(cards),
        "count_all_英文": count_all_en,
        "count_all_中文": count_all_cn,
        "count_bombs": c.count_bombs(),
        "has_rocket": ("JOKER_B" in cards and "JOKER_S" in cards),
    }


def analyze_deal(deal_json_text: str, with_combinations: bool = False) -> dict:
    """分析一整副 deal(4 玩家 + 底牌),返回每玩家的所有属性。

    Args:
        deal_json_text: DealResult JSON 字符串(可用 deal_hand 生成)。
        with_combinations: 是否包含每玩家的牌型识别(默认 False,数据量小)。

    Returns:
        dict: 包含
            - all_players: {pid -> {属性 -> 值}}
              属性: bomb_count, has_rocket, has_wild_card, joker_count,
                   card_count, level_card_count, rank_histogram, combinations(可选)
            - wild_card: 红心配级牌(如 H2)
            - wild_card_owner: 持有者 pid / "bottom"
            - level_rank: 级牌
    """
    deal = json.loads(deal_json_text)
    a = Analyzer(deal)
    result = a.all_players()
    result["wild_card"] = a.wild_card
    result["wild_card_owner"] = a.wild_card_owner
    if not with_combinations:
        result.pop("combinations", None)
    return result


def analyze_attribute(deal_json_text: str, attribute: str) -> dict:
    """查询一整副 deal 中每位玩家的单个属性。

    Args:
        deal_json_text: DealResult JSON 字符串(可用 deal_hand 生成)。
        attribute: 属性名,可选: bomb_count, has_rocket, has_wild_card,
                   joker_count, card_count, level_card_count, rank_histogram。

    Returns:
        dict: 包含 attribute、values({pid -> 值})、level_rank、wild_card、
              wild_card_owner。
    """
    if attribute not in VALID_ATTRIBUTES:
        raise ValueError(f"未知属性: {attribute!r}。可选: {', '.join(VALID_ATTRIBUTES)}")
    deal = json.loads(deal_json_text)
    analyzer = Analyzer(deal)
    values = getattr(analyzer, attribute)()
    return {
        "attribute": attribute,
        "values": values,
        "level_rank": analyzer.level_rank,
        "wild_card": analyzer.wild_card,
        "wild_card_owner": analyzer.wild_card_owner,
    }


def frequency(file_path: str, query: str) -> dict:
    """查询一手牌某属性的频率分布(基于 JSONL 批量样本)。

    内置 3000 局样本路径: 内置样本(请传 'BUILTIN' 或留空 — 实际见工具)
    或上传自己的 JSONL 路径(HF Spaces 上传文件后会得到绝对路径)。

    Args:
        file_path: JSONL 文件路径,或 "BUILTIN" 使用内置 3000 局样本。
        query: 属性名,可选: has_rocket, has_wild_card, joker_count,
               card_count, level_card_count, bomb_count, rank_histogram。

    Returns:
        dict: {query: {value: 出现次数}} 或 {query: {value_str: count}}。
    """
    path = _resolve_batch_path(file_path)
    stats = Stats.from_file(str(path))
    try:
        return {query: stats.frequency(query)}
    except (AttributeError, KeyError):
        return {query: stats.frequency_dist(query)}


def contradiction(type_x: str, type_y: str, file_path: str = "BUILTIN") -> dict:
    """查询两个牌型之间的负相关(Pearson r)。「X 多则 Y 少」的程度。

    强负相关(r < -0.15) = 两牌型互斥: 凑 X 后 Y 明显少。
    弱正相关(r > 0) = 两牌型倾向于同时出现。

    Args:
        type_x: 牌型 X(中文或英文,见 list_牌型)
        type_y: 牌型 Y(同上)
        file_path: JSONL 文件路径(默认内置 3000 局)

    Returns:
        dict: {X, Y, pearson_r, strength, interpretation}
        其中 strength ∈ "强负相关" | "中负相关" | "弱负相关" | "弱正相关" | "无关"
    """
    x = _resolve_type(type_x)
    y = _resolve_type(type_y)
    path = _resolve_batch_path(file_path)
    xs, ys = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        level = d.get("level_rank", "2")
        for hand in d["hands"].values():
            ca = Combinations(hand, level).count_all()
            xs.append(ca[x])
            ys.append(ca[y])
    r = _pearson(xs, ys)
    return {
        "X": EN_TO_CN.get(x, x),
        "Y": EN_TO_CN.get(y, y),
        "pearson_r": round(r, 4),
        "strength": _corr_strength(r),
        "interpretation": _interpret_corr(x, y, r),
    }


def top_correlations(threshold: float = -0.1, top_n: int = 10) -> list[dict]:
    """列出最强的几个负相关牌型对(基于内置 3000 局样本)。

    适合回答"哪些牌型互相矛盾"、"凑出 X 后 Y 明显少"等问题。

    Args:
        threshold: 相关系数阈值(默认 -0.1,只返回 r ≤ threshold 的对)
        top_n: 返回前 N 对(默认 10)

    Returns:
        list of dict: [{X, Y, pearson_r}, ...] 按 r 升序(最强负相关在前)
    """
    if not BUILTIN_BATCH_AVAILABLE:
        return [{"error": "内置样本不可用"}]
    # 收集所有牌的 count
    data = {t: [] for t in SUPPORTED_TYPES}
    for line in BUILTIN_BATCH_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        level = d.get("level_rank", "2")
        for hand in d["hands"].values():
            ca = Combinations(hand, level).count_all()
            for t in SUPPORTED_TYPES:
                data[t].append(ca[t])
    pairs = []
    for i, x in enumerate(SUPPORTED_TYPES):
        for y in SUPPORTED_TYPES[i + 1 :]:
            r = _pearson(data[x], data[y])
            if r <= threshold:
                pairs.append({"X": EN_TO_CN[x], "Y": EN_TO_CN[y], "pearson_r": round(r, 4)})
    pairs.sort(key=lambda p: p["pearson_r"])
    return pairs[: int(top_n)]


def top_hand_types(top_n: int = 10) -> list[dict]:
    """列出出现概率最高的牌型(基于内置 3000 局、12000 玩家手)。

    Args:
        top_n: 返回前 N 种牌型,范围 1-15(默认 10)。

    Returns:
        list of dict: [{排名, 中文, 英文, 出现概率, 平均每手}, ...],
        按「一手中至少出现 1 个」的概率降序排列。
    """
    if not BUILTIN_BATCH_AVAILABLE:
        return [{"error": "内置样本不可用"}]
    present: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    hand_count = 0
    for line in BUILTIN_BATCH_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        deal = json.loads(line)
        level = deal.get("level_rank", "2")
        for hand in deal["hands"].values():
            counts = Combinations(hand, level).count_all()
            hand_count += 1
            for type_name, count in counts.items():
                totals[type_name] += count
                if count > 0:
                    present[type_name] += 1
    ranked = sorted(SUPPORTED_TYPES, key=lambda name: (-present[name], name))
    limit = max(1, min(int(top_n), len(SUPPORTED_TYPES)))
    return [
        {
            "排名": index,
            "中文": EN_TO_CN[type_name],
            "英文": type_name,
            "出现概率": round(present[type_name] / hand_count, 6),
            "平均每手": round(totals[type_name] / hand_count, 4),
            "样本手数": hand_count,
        }
        for index, type_name in enumerate(ranked[:limit], start=1)
    ]


def list_牌型() -> dict:
    """返回 15 种牌型的中英文名 + 简要规则,供智能体理解。

    Returns:
        dict: {"15_牌型": [{"英文": "single", "中文": "单张", "规则": "..."}, ...]}
    """
    rules = {
        "single": "任意 1 张牌",
        "pair": "同 rank × 2(排除级牌)",
        "triple": "同 rank × 3(排除级牌)",
        "bomb_4": "同 rank × 4(排除级牌)",
        "bomb_5": "同 rank × 5",
        "bomb_6": "同 rank × 6",
        "bomb_7": "同 rank × 7",
        "bomb_8": "同 rank × 8(2 副牌上限)",
        "triple_with_single": "三张 + 任意单张",
        "triple_with_pair": "三张 + 任意对子",
        "straight": "5+ 连续 rank(3..A),含 A2345 最小",
        "tube": "3+ 连续对(连对)",
        "plate": "2+ 连续三张(钢板)",
        "straight_flush": "5+ 同花连续(同花顺)",
        "joker_bomb": "同时持有 4 张大小王(天王炸)",
    }
    return {"15_牌型": [{"英文": k, "中文": CN_NAME[k], "规则": rules[k]} for k in SUPPORTED_TYPES]}


def simulate_deals(num_deals: int, base_seed: int = 0) -> dict:
    """生成 N 局 deal 样本(用于自己跑统计)。

    Args:
        num_deals: 生成局数(建议 ≤ 10000)
        base_seed: 起始种子

    Returns:
        dict: {count, base_seed, deals: [deal_dict, ...]}
    """
    deals = []
    for i in range(int(num_deals)):
        deals.append(Dealer.deal(seed=int(base_seed) + i).to_dict())
    return {"count": len(deals), "base_seed": int(base_seed), "deals": deals}


def parse_card(card_text: str) -> str:
    """自然语言牌面 → 内部代号。如 "红心A" → "HA"。

    支持花色: 红心/心(H), 黑桃/桃(S), 方片/方(D), 梅花/梅/花(C)
    支持数字: 2-9, 10/十/T, J, Q, K, A/1/一
    支持大小王: 大王/大鬼, 小王/小鬼

    Args:
        card_text: 自然语言牌面,大小写不敏感

    Returns:
        str: 内部代号, 如 "HA", "S2", "JOKER_B"
    """
    from guandan_model.cards import parse

    return parse(card_text)


def render_card(code: str, chinese: bool = False) -> str:
    """内部代号 → 自然语言牌面。如 "HA" → "红心A"。

    Args:
        code: 内部代号, 如 "HA", "ST", "JOKER_B"
        chinese: True 输出中文(红心/黑桃等), False 输出紧凑 ASCII

    Returns:
        str: 渲染后字符串
    """
    return render(code, chinese=chinese)


# ---------- 辅助函数 ----------


def _resolve_batch_path(file_path: str) -> Path:
    """解析批次文件路径。BUILTIN 或空 → 内置样本。"""
    if not file_path or file_path.upper() == "BUILTIN":
        if not BUILTIN_BATCH_AVAILABLE:
            raise FileNotFoundError("内置 3000 局样本不可用")
        return BUILTIN_BATCH_PATH
    return Path(file_path)


def _resolve_type(name: str) -> str:
    """中英文牌型名 → 英文 key。"""
    if name in SUPPORTED_TYPES:
        return name
    if name in CN_TO_EN:
        return CN_TO_EN[name]
    raise ValueError(f"未知牌型: {name!r}。{VALID_TYPE_NAMES}")


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _corr_strength(r: float) -> str:
    if r <= -0.2:
        return "强负相关"
    if r <= -0.1:
        return "中负相关"
    if r <= -0.05:
        return "弱负相关"
    if r >= 0.05:
        return "弱正相关"
    return "几乎无关"


def _interpret_corr(x: str, y: str, r: float) -> str:
    """给一个直观的解读,供智能体直接引用。"""
    x_cn = EN_TO_CN.get(x, x)
    y_cn = EN_TO_CN.get(y, y)
    if r <= -0.2:
        return f"强矛盾: {x_cn} 多的手,{y_cn} 明显少(典型同 rank 或跨 rank 互斥)"
    if r <= -0.1:
        return f"中矛盾: {x_cn} 多了 {y_cn} 会被压缩"
    if r <= -0.05:
        return f"弱矛盾: {x_cn} 和 {y_cn} 略有互斥"
    if r >= 0.05:
        return f"同向: {x_cn} 和 {y_cn} 倾向于同时出现"
    return f"几乎独立: {x_cn} 和 {y_cn} 互不影响"


# ---------- Gradio UI + MCP tools ----------


def build_demo() -> gr.Blocks:
    """构建 Gradio Blocks demo,每个函数即一个 MCP tool。"""
    with gr.Blocks(title="掼蛋发牌模型 v0.5") as demo:
        gr.Markdown(
            "# 🎴 掼蛋发牌模型 v0.5\n"
            "MCP 服务(给智能体用) + Web UI(给人类用)。\n"
            "**MCP 端点**: `/gradio_api/mcp/`(供 Claude Code / OpenCode 等接入)"
        )

        with gr.Tab("🎲 发牌"):
            with gr.Row():
                seed_in = gr.Number(label="种子", value=42, precision=0)
                level_in = gr.Textbox(label="级牌", value="2")
            deal_btn = gr.Button("发牌", variant="primary")
            deal_out = gr.JSON(label="DealResult")
            deal_btn.click(
                fn=deal_hand,
                inputs=[seed_in, level_in],
                outputs=deal_out,
                api_name="deal_hand",
            )

        with gr.Tab("🃏 单手牌型识别"):
            gr.Markdown("**输入**: 空格分隔的牌代号(HA SA DA CA H3 H4 H5)")
            hand_in = gr.Textbox(
                label="手牌", value="HA SA DA CA H3 H4 H5", placeholder="HA SA DA CA"
            )
            hand_level = gr.Textbox(label="级牌", value="2")
            hand_btn = gr.Button("分析手牌", variant="primary")
            hand_out = gr.JSON(label="牌型识别结果")
            hand_btn.click(
                fn=analyze_hand,
                inputs=[hand_in, hand_level],
                outputs=hand_out,
                api_name="analyze_hand",
            )

        with gr.Tab("📊 单 deal 全分析"):
            gr.Markdown("**输入**: DealResult JSON(可由「发牌」标签生成后粘贴)")
            deal_json_in = gr.Textbox(
                label="DealResult JSON",
                value=DEFAULT_DEAL_JSON,
                lines=6,
            )
            with_combo = gr.Checkbox(label="包含牌型识别(数据量大)", value=False)
            deal_analyze_btn = gr.Button("分析", variant="primary")
            deal_analyze_out = gr.JSON(label="分析结果")
            deal_analyze_btn.click(
                fn=analyze_deal,
                inputs=[deal_json_in, with_combo],
                outputs=deal_analyze_out,
                api_name="analyze_deal",
            )
            attribute_in = gr.Dropdown(
                choices=list(VALID_ATTRIBUTES), label="单属性", value="bomb_count"
            )
            attribute_btn = gr.Button("查询单个属性")
            attribute_out = gr.JSON(label="单属性结果")
            attribute_btn.click(
                fn=analyze_attribute,
                inputs=[deal_json_in, attribute_in],
                outputs=attribute_out,
                api_name="analyze_attribute",
            )

        with gr.Tab("📈 频率统计"):
            gr.Markdown(
                "**输入**: JSONL 路径(留空用内置 3000 局) + 属性名。"
                "可用属性: has_rocket, has_wild_card, joker_count, card_count, "
                "level_card_count, bomb_count, rank_histogram"
            )
            freq_file = gr.Textbox(label="JSONL 路径", value="BUILTIN")
            freq_query = gr.Dropdown(
                choices=[
                    "has_rocket",
                    "has_wild_card",
                    "joker_count",
                    "card_count",
                    "level_card_count",
                    "bomb_count",
                    "rank_histogram",
                ],
                label="属性",
                value="bomb_count",
            )
            freq_btn = gr.Button("查询", variant="primary")
            freq_out = gr.JSON(label="频率分布")
            freq_btn.click(
                fn=frequency,
                inputs=[freq_file, freq_query],
                outputs=freq_out,
                api_name="frequency",
            )
            top_type_n = gr.Slider(minimum=1, maximum=15, step=1, value=10, label="高概率牌型数量")
            top_type_btn = gr.Button("查询高概率牌型")
            top_type_out = gr.JSON(label="高概率牌型")
            top_type_btn.click(
                fn=top_hand_types,
                inputs=top_type_n,
                outputs=top_type_out,
                api_name="top_hand_types",
            )

        with gr.Tab("⚡ 矛盾分析"):
            gr.Markdown("**输入**: 两个牌型(中文或英文)+ Pearson 阈值")
            with gr.Row():
                cx = gr.Dropdown(choices=list(EN_TO_CN.values()), label="牌型 X", value="4张炸")
                cy = gr.Dropdown(choices=list(EN_TO_CN.values()), label="牌型 Y", value="5张炸")
            cth = gr.Slider(
                minimum=-0.5, maximum=0.5, step=0.05, value=-0.05, label="r 阈值(只显示 ≤ 此值的对)"
            )
            ctop = gr.Slider(minimum=1, maximum=30, step=1, value=10, label="返回前 N 对")
            c_btn = gr.Button("查两牌型", variant="primary")
            c_out = gr.JSON(label="两牌型负相关")
            c_btn.click(fn=contradiction, inputs=[cx, cy], outputs=c_out, api_name="contradiction")
            ct_btn = gr.Button("查 Top 矛盾对", variant="primary")
            ct_out = gr.JSON(label="Top 矛盾牌型对")
            ct_btn.click(
                fn=top_correlations,
                inputs=[cth, ctop],
                outputs=ct_out,
                api_name="top_correlations",
            )

        with gr.Tab("📚 牌型字典"):
            list_btn = gr.Button("列出 15 牌型", variant="primary")
            list_out = gr.JSON(label="15 牌型(中英文 + 规则)")
            list_btn.click(fn=list_牌型, inputs=[], outputs=list_out, api_name="list_牌型")

        with gr.Tab("🛠 工具函数"):
            with gr.Row():
                parse_in = gr.Textbox(label="自然语言牌面", value="红心A")
                parse_out = gr.Textbox(label="内部代号")
            parse_btn = gr.Button("parse_card")
            parse_btn.click(
                fn=parse_card,
                inputs=parse_in,
                outputs=parse_out,
                api_name="parse_card",
            )
            with gr.Row():
                render_in = gr.Textbox(label="内部代号", value="HA")
                render_zh = gr.Checkbox(label="中文", value=True)
                render_out = gr.Textbox(label="渲染结果")
            render_btn = gr.Button("render_card")
            render_btn.click(
                fn=render_card,
                inputs=[render_in, render_zh],
                outputs=render_out,
                api_name="render_card",
            )
            with gr.Row():
                sim_n = gr.Number(label="生成局数", value=10, precision=0)
                sim_seed = gr.Number(label="起始种子", value=0, precision=0)
            sim_btn = gr.Button("simulate_deals")
            sim_out = gr.JSON(label="生成结果")
            sim_btn.click(
                fn=simulate_deals,
                inputs=[sim_n, sim_seed],
                outputs=sim_out,
                api_name="simulate_deals",
            )

    return demo


# ---------- 入口 ----------


demo = build_demo()

if __name__ == "__main__":
    # HF Spaces 会传入 PORT 环境变量
    port = int(os.environ.get("PORT", 7860))
    demo.launch(
        server_name="0.0.0.0",
        server_port=port,
        mcp_server=True,
    )
