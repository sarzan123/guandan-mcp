---
title: Guandan MCP
emoji: 🃏
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 6.20.0
python_version: '3.12'
app_file: app.py
pinned: false
license: mit
---

# 掼蛋发牌模型 — Hugging Face Spaces MCP Server

把本目录推到 Hugging Face Spaces (Gradio SDK) 即得到一个公开的 MCP 端点，
朋友的 Claude Code / OpenCode / Hermes Agent / Cline / Cursor 等智能体
可以直接调用本服务回答掼蛋问题。

> 服务名:掼蛋发牌模型 v0.5
> 端点:`https://sarzan123-guandan-model.hf.space/gradio_api/mcp/`
> 协议:Model Context Protocol (MCP) over HTTP

---

## MCP 工具清单(12 个)

| 工具 | 用途 | 关键参数 |
|---|---|---|
| `deal_hand` | 按种子发牌 | `seed`, `level_rank` |
| `analyze_hand` | 单手牌 15 牌型识别 | `hand_text`, `level_rank` |
| `analyze_deal` | 整副 deal 全属性分析 | `deal_json_text`, `with_combinations` |
| `analyze_attribute` | 整副 deal 单属性查询 | `deal_json_text`, `attribute` |
| `frequency` | 频率分布(基于 JSONL 样本) | `file_path`, `query` |
| `contradiction` | 两牌型 Pearson 负相关 | `type_x`, `type_y`, `file_path` |
| `top_correlations` | Top 负相关牌型对 | `threshold`, `top_n` |
| `top_hand_types` | 高出现概率牌型 | `top_n` |
| `list_牌型` | 15 牌型中英文 + 规则 | — |
| `simulate_deals` | 批量生成 deal | `num_deals`, `base_seed` |
| `parse_card` | 自然语言 → 内部代号 | `card_text` |
| `render_card` | 内部代号 → 自然语言 | `code`, `chinese` |

详细输入/输出规范见 `app.py` 中每个函数的中文 docstring —— 智能体会读到这些 docstring。

---

## 朋友如何配置(把本服务接入他的智能体)

### Claude Code

在 `~/.claude/mcp_servers.json` (或项目根的 `.mcp.json`) 添加:

```json
{
  "mcpServers": {
    "guandan": {
      "url": "https://sarzan123-guandan-model.hf.space/gradio_api/mcp/",
      "transport": "streamable-http"
    }
  }
}
```

重启 Claude Code,新会话里就能看到 `guandan` 提供的 12 个工具。

### OpenCode

`~/.config/opencode/config.yaml`:

```yaml
mcp:
  guandan:
    url: https://sarzan123-guandan-model.hf.space/gradio_api/mcp/
    transport: streamable-http
```

### Hermes Agent / Cline / Cursor

均按其官方文档添加一个 "Streamable HTTP" MCP server,URL 填上面的端点即可。

---

## 示例问题(朋友可直接问智能体)

- "我有一手牌 HA SA DA CA H3 H4 H5 H6 H7,有哪些牌型?"
- "4 张炸的概率是多少?基于内置 3000 局样本"
- "哪些牌型互斥最强?"
- "按种子 42 给我发一副牌,然后分析每玩家的炸弹数"
- "用中文告诉我 15 种牌型的规则"

---

## 数据源说明

内置 3000 局样本 (`data/batch_3000.jsonl`, ~2.6 MB) 用于 `frequency` / `contradiction` / `top_correlations` / `top_hand_types`。

---

## 版本与限制

- v0.5 牌型识别 + 矛盾/频率统计;**Dealer 当前固定级牌为 2** (v0 限制)。
- HF Spaces 免费层有 CPU 配额,3000 局统计约 2-3 秒,够用。
- MCP 协议要求客户端支持 Streamable HTTP (Claude Code ≥ 1.0, OpenCode ≥ 0.4, Hermes Agent, Cline ≥ 3.5)。
