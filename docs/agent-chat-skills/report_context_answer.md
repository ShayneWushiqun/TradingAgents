# 报告上下文回答 Skill

## 触发场景

- 用户从工作台打开 Agent Chat，并围绕当前 `task_id` 追问报告结论。
- 用户询问风险、预期、估值压力、交易计划、买卖评级或各 Agent 分歧。
- 用户要求总结、解释、翻译或复盘当前 TradingAgents 分析报告。
- 用户没有要求新增外部数据，且已有报告足以回答问题。

## 输入参数

- `task_id`: 必填，当前分析任务 ID。
- `message`: 用户问题。
- `ts_code`: 可选，用于校验任务对应标的。
- `trade_date`: 可选，用于校验任务日期。
- `sections`: 可选报告区块列表，例如 `market_report`、`fundamentals_report`、`news_report`、`sentiment_report`、`final_trade_decision`。
- `include_sources`: 是否在回答中列出引用的报告区块，默认 true。

## 可调用数据源

- 当前任务的 TradingAgents 报告上下文。
- 分阶段报告区块：market、fundamentals、news、sentiment、investment debate、risk debate、final decision。
- 本地分析缓存和持久化任务索引。
- Tushare、AKShare 和 Tavily 仅在报告上下文不足、用户要求更新事实或需要核验时调用。

## 6000+ Tushare 积分下默认允许的接口

报告上下文回答默认不主动调用 Tushare；当用户要求核验报告中的数据或补充结构化证据时，可默认允许：

- `stock_basic`: 校验标的基础信息。
- `trade_cal`: 校验交易日。
- `daily`: 复核行情表现。
- `daily_basic`: 复核估值、换手率和成交指标。
- `moneyflow`: 复核资金流。
- `income`: 复核利润表摘要。
- `balancesheet`: 复核资产负债表摘要。
- `cashflow`: 复核现金流量表摘要。
- `fina_indicator`: 复核关键财务指标。
- `forecast`: 复核业绩预告。
- `express`: 复核业绩快报。

## 需要额外权限时如何降级

- 找不到 `task_id` 时，提示用户回到工作台重新打开 Agent Chat，或使用最近一次分析任务。
- 报告未完成时，只基于已生成区块回答，并明确说明最终决策尚未就绪。
- 报告区块缺失时，优先使用相邻区块和 final decision；仍不足时说明无法从当前报告判断。
- Tushare 权限不足或外部数据不可用时，不阻塞报告问答，回退到已有报告上下文。
- 用户要求实时事实但外部搜索不可用时，明确回答“当前仅基于报告，不包含最新外部信息”。
- 不输出或记录任何 token、环境变量值或鉴权细节。

## 返回格式

```json
{
  "skill": "report_context_answer",
  "status": "ok | partial | unavailable",
  "task_id": "任务 ID",
  "answer": "面向用户的自然语言回答。",
  "used_sections": [
    "market_report",
    "fundamentals_report",
    "final_trade_decision"
  ],
  "follow_up_data_needed": [
    {
      "reason": "需要外部数据的原因",
      "suggested_skill": "tushare_a_share_data | a_share_news_search"
    }
  ],
  "limitations": ["报告未完成、区块缺失或降级说明"]
}
```
