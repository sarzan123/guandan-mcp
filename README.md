# 掼蛋发牌模型 v0.5 — MCP Server (Render 部署)

公开 MCP 端点,朋友的 Claude Code / OpenCode / Hermes Agent / Cline / Cursor 等智能体
可以直接调用本服务回答掼蛋问题。

> 服务:掼蛋发牌模型 v1.1
> 协议:Model Context Protocol (MCP) over HTTP
> 平台:Render.com 免费 Docker Web Service
>
> **v1.1 修复**: 真实掼蛋 = 4×27=108(无底牌)。v0 的 4×25+8 错误模型已删除。

---

## 公网 URL(部署完成后会形如下)

| 用途 | URL |
|---|---|
| Web UI(浏览器看) | https://guandan-mcp.onrender.com/ |
| **MCP 端点**(智能体接)| https://guandan-mcp.onrender.com/gradio_api/mcp/ |

`guandan-mcp` 是 Render 默认按 service name 生成的子域名,可在 Render dashboard 改名。

---

## 一键部署步骤

### 0. 前置(5 分钟)

- 一个 **GitHub 账号**(用来托管本仓库 + Render 自动部署)
- 一个 **Render.com 账号** → https://dashboard.render.com/register(用 GitHub 登录)

### 1. 把代码推到 GitHub

```bash
# 1) 在 GitHub 网页创建一个新 repo(空仓库)
#    名:guandan-mcp
#    描述:GuanDan MCP server (Gradio 5.x + 12 tools)

# 2) 把本地 deploy/ 切换 remote 到 GitHub,然后 push
cd C:/code/掼蛋模型/deploy
git remote remove origin
git remote add origin https://github.com/sarzan123/guandan-mcp.git
git push -u origin main
```

> 这一步会把我之前给你的 8 个 fix commits + 这次 Render 改动一并推上去。
> Render 看不到 HF 了 — HF Space 我建议手动从 dashboard 删除。

### 2. Render 接 GitHub 部署

1. 打开 https://dashboard.render.com/blueprints
2. 点 **New Blueprint Instance**
3. 选 **GitHub**(第一次会要求授权)
4. 选你刚 push 的 `sarzan123/guandan-mcp` repo
5. Render 自动读 `render.yaml` → 显示 1 个 service(guandan-mcp, free, Docker)
6. 点 **Apply** → 开始构建

### 3. 等构建

- 第一次构建要拉 `python:3.12-slim` + 装 Gradio 5.x ≈ 3-5 分钟
- Logs 在 Render dashboard service 页面
- 构建成功后,Render 自动给个 URL,例如 `https://guandan-mcp.onrender.com/`

### 4. 测试

浏览器打开那个 URL,看到 Gradio Web UI = 部署成功。
MCP 端点:`https://guandan-mcp.onrender.com/gradio_api/mcp/`

---

## 朋友如何配置(把本服务接入他的智能体)

### Claude Code

`~/.claude/mcp_servers.json`(或项目根的 `.mcp.json`):

```json
{
  "mcpServers": {
    "guandan": {
      "url": "https://guandan-mcp.onrender.com/gradio_api/mcp/",
      "transport": "streamable-http"
    }
  }
}
```

### OpenCode / Hermes Agent / Cline / Cursor

URL 替换成上面那行即可。具体 YAML/JSON 格式参各自文档。

---

## MCP 工具清单(12 个)

| 工具 | 用途 |
|---|---|
| `deal_hand` | 按种子发牌 |
| `analyze_hand` | 单手牌 15 牌型识别 |
| `analyze_deal` | 整副 deal 全属性分析 |
| `analyze_attribute` | 整副 deal 单属性查询 |
| `frequency` | 频率分布(基于 JSONL 样本) |
| `contradiction` | 两牌型 Pearson 负相关 |
| `top_correlations` | Top 负相关牌型对 |
| `top_hand_types` | 高出现概率牌型 |
| `list_牌型` | 15 牌型中英文 + 规则 |
| `simulate_deals` | 批量生成 deal |
| `parse_card` | 自然语言 → 内部代号 |
| `render_card` | 内部代号 → 自然语言 |

中文 docstring 在 `app.py`,智能体会直接读到。

---

## 免费层注意事项

- **Render 免费 Web Service 闲置 15 分钟后会休眠**;下次冷启动 ≈ 30 秒。
- 给朋友发 URL 时,他们的智能体首次调用会有 30 秒左右延迟,之后实时。
- 想全天候秒响应 → 升级 Render Starter($7/月,免睡)。
- 防止休眠的小技巧:用 `cron-job.org`(免费)每 14 分钟 ping 一下 Web UI URL。

---

## 已知差异(从 HF Space 迁移)

- 部署平台从 Hugging Face 改为 Render
- 公开 URL 域名从 `.hf.space` 改为 `.onrender.com`
- Gradio 版本 pin 仍是 `>=5.6,<6`,Dockerfile 用 `python:3.12-slim`
- 不再有 ZeroGPU / `@spaces.GPU` 约束
- 旧 HF Space 建议在 https://huggingface.co/settings/spaces 手动删除(腾配额)

---

## 版本与限制

- v0.5 牌型识别 + 矛盾/频率统计;Dealer 当前固定级牌为 2。
- 3000 局统计约 2-3 秒。
- MCP 协议要求客户端支持 Streamable HTTP(Claude Code ≥ 1.0, OpenCode ≥ 0.4, Cline ≥ 3.5)。
