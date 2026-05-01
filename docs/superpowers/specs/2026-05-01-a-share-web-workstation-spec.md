# A 股单股分析工作台 Spec

## 目标

为当前 TradingAgents 项目增加一个可打开、可运行的 Web 前端页面。首版聚焦单只 A 股：用户输入 `600519.SH` 这类 Tushare 股票代码，后端读取 `.env` 中的 `TUSHARE_API_TOKEN` 获取常规 A 股数据，运行现有 TradingAgents 多智能体流程，并在页面上展示行情概览、分析进度、最终报告和基于报告上下文的 Agent Chat。

## 非目标

- 不做自选股、批量分析、组合管理。
- 不默认依赖新闻、公告、研报、分钟行情或实时行情，因为这些在 Tushare 中多为单独权限或额外开通能力。
- 不保存用户的 Tushare token 到浏览器或前端代码。
- 不在首版实现真实下单、交易执行或投资建议自动执行。

## 用户流程

1. 用户打开 Web 页面。
2. 页面显示单股分析表单、Tushare Pro 数据源状态、A 股常规接口可用范围。
3. 用户输入股票代码、分析交易日，选择分析师和研究深度。
4. 用户点击“开始分析”。
5. 后端创建分析任务，加载 Tushare 数据，运行 TradingAgentsGraph。
6. 页面显示 agent 进度：Market Analyst、Fundamentals、News/Optional、Research Debate、Trader、Portfolio Manager。
7. 任务完成后，页面展示结构化报告摘要、最终决策、核心理由、风险提示。
8. 用户点击“开启 Agent 对话”，页面将本次报告作为上下文，用户可以继续追问当前股票的风险、预期或交易计划。

## 数据源策略

首版只默认使用当前积分可稳定覆盖的 Tushare 常规接口：

- `daily`: A 股日线行情。
- `pro_bar`: 复权行情，用于趋势和技术指标基础数据。
- `daily_basic`: 每日指标，如 PE、PB、换手率、市值。
- `income`: 利润表。
- `balancesheet`: 资产负债表。
- `cashflow`: 现金流量表。
- `fina_indicator`: 财务指标。
- `moneyflow`: 个股资金流向。

增强能力只做提示，不作为首版依赖：

- 新闻资讯。
- 公告信息。
- 券商研报。
- 分钟行情。
- 实时行情。

## 后端接口

后端采用 FastAPI，提供静态页面和 JSON/SSE API。

### `GET /`

返回前端页面。

### `GET /api/health`

返回服务状态、Tushare token 是否已配置、当前数据源模式。

响应示例：

```json
{
  "ok": true,
  "data_source": "tushare",
  "tushare_configured": true
}
```

### `GET /api/tushare/stocks/{ts_code}/snapshot?trade_date=YYYY-MM-DD`

返回页面顶部行情概览和图表所需数据。

响应示例：

```json
{
  "ts_code": "600519.SH",
  "name": "贵州茅台",
  "trade_date": "2026-04-30",
  "price": {
    "close": 1684.2,
    "pct_chg": 1.82,
    "amount": 4260000000
  },
  "daily_basic": {
    "pe_ttm": 28.4,
    "pb": 8.2,
    "total_mv": 2110000000000
  },
  "ohlcv": []
}
```

### `POST /api/analysis`

创建单股分析任务。

请求示例：

```json
{
  "ts_code": "600519.SH",
  "trade_date": "2026-04-30",
  "analysts": ["market", "fundamentals"],
  "research_depth": 1,
  "llm_provider": "deepseek",
  "quick_model": "deepseek-chat",
  "deep_model": "deepseek-chat"
}
```

响应示例：

```json
{
  "task_id": "20260501-600519-SH-001",
  "status": "queued"
}
```

### `GET /api/analysis/{task_id}/events`

SSE 事件流，推送 agent 进度和报告片段。

事件类型：

- `task_started`
- `agent_started`
- `agent_completed`
- `report_section`
- `task_completed`
- `task_failed`

### `GET /api/analysis/{task_id}`

返回任务当前状态、报告 sections、最终决策。

### `POST /api/chat`

使用某个分析任务的报告作为上下文，调用当前配置的 LLM 返回追问结果。

请求示例：

```json
{
  "task_id": "20260501-600519-SH-001",
  "message": "如果未来两周成交额下降，这个增持判断要怎么调整？"
}
```

## 前端要求

首版沿用 `docs/design/a-share-workstation.html` 的页面结构，迁移为可由后端服务的静态页面。

必须具备：

- 单股输入。
- Tushare Pro 状态区。
- 常规投研接口和增强权限提示。
- 股票概览指标。
- 图表占位或简化 SVG 图表。
- 多智能体进度。
- 最终决策面板。
- Agent Chat 历史 thread 与对话区。

## 状态管理

首版使用后端内存任务存储：

- `task_id`
- 请求参数。
- 当前状态。
- agent 进度。
- 报告 sections。
- 最终决策。
- chat messages。

进程重启后任务丢失可以接受。后续再接 SQLite 或现有 report/memory 文件。

## 错误处理

- Tushare token 未配置：页面显示“Token 未配置”，禁用“开始分析”。
- Tushare 接口权限不足：返回明确接口名和建议，例如“该数据需要单独权限，首版已跳过”。
- LLM provider 未配置：允许先拉取 Tushare snapshot，但分析任务返回可读错误。
- 分析任务失败：页面保留已完成 sections，并显示失败 agent 和错误摘要。

## 测试要求

- FastAPI health endpoint 测试。
- Tushare adapter 使用 fake client 测试，不调用真实网络。
- 股票代码校验测试：只允许 `.SH`、`.SZ`、`.BJ`。
- 分析任务服务测试：能创建任务、记录进度、返回最终状态。
- 静态页面 smoke 测试：文件包含核心 UI 区域和 API 调用钩子。

## 交付标准

- 能用一个命令启动 Web 服务。
- 浏览器打开 `http://127.0.0.1:<port>/` 能看到页面。
- `.env` 中的 `TUSHARE_API_TOKEN` 由后端加载。
- 页面能调用后端 health 和 snapshot API。
- 在没有真实 LLM 或外部网络受限时，提供明确错误，不白屏。
- 代码测试通过，至少覆盖后端边界和页面 smoke。
