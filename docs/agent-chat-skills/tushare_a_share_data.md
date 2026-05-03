# Tushare A股数据 Skill

## 触发场景

- 用户在 Agent Chat 中追问 A 股行情、估值、财务、资金流、公司基础资料或交易日数据。
- 当前报告缺少可验证的量化数据，需要用结构化数据补充回答。
- 用户明确给出 `ts_code`、股票简称、交易日或区间，并要求对比、复核或解释指标变化。

## 输入参数

- `ts_code`: A 股证券代码，优先使用 Tushare 标准格式，例如 `600519.SH`、`000066.SZ`。
- `trade_date`: 单日查询日期，格式为 `YYYYMMDD` 或可转换的 `YYYY-MM-DD`。
- `start_date`: 区间开始日期，格式同上。
- `end_date`: 区间结束日期，格式同上。
- `fields`: 可选字段列表；默认按回答需要选择最小字段集。
- `question`: 用户原始问题，用于判断应查询行情、财务、资金流还是基础资料。
- `task_id`: 可选分析任务 ID，用于和报告上下文合并。

## 可调用数据源

- Tushare Pro A 股行情接口。
- Tushare Pro 上市公司基础资料接口。
- Tushare Pro 财务指标、利润表、资产负债表、现金流量表接口。
- Tushare Pro 资金流、每日指标、复权因子和交易日历接口。
- 当前 TradingAgents 报告上下文，用于解释数据和已有结论之间的关系。

## 6000+ Tushare 积分下默认允许的接口

- `stock_basic`: 股票基础信息。
- `trade_cal`: 交易日历。
- `daily`: 日线行情。
- `weekly`: 周线行情。
- `monthly`: 月线行情。
- `adj_factor`: 复权因子。
- `daily_basic`: 每日基础指标。
- `moneyflow`: 个股资金流向。
- `income`: 利润表。
- `balancesheet`: 资产负债表。
- `cashflow`: 现金流量表。
- `fina_indicator`: 财务指标。
- `forecast`: 业绩预告。
- `express`: 业绩快报。
- `dividend`: 分红送股。
- `stk_holdernumber`: 股东人数。

## 需要额外权限时如何降级

- 如果接口返回权限不足，先尝试同主题的低权限接口，例如用 `daily` + `daily_basic` 替代更高阶行情统计。
- 如果财务明细接口不可用，降级到已缓存报告中的 fundamentals 结论，并明确说明没有拿到新增明细。
- 如果区间过长导致调用失败，缩短为近 60 至 120 个交易日，并在回答中说明采样窗口。
- 如果股票代码无法解析，先要求用户确认代码或市场后缀，不猜测具体标的。
- 不输出或记录任何 token、环境变量值或鉴权细节。

## 返回格式

```json
{
  "skill": "tushare_a_share_data",
  "status": "ok | partial | unavailable",
  "data_sources": ["tushare"],
  "query": {
    "ts_code": "600519.SH",
    "start_date": "20260401",
    "end_date": "20260430",
    "interfaces": ["daily", "daily_basic"]
  },
  "summary": "面向用户的简洁结论。",
  "evidence": [
    {
      "label": "收盘价变化",
      "value": "示例值",
      "as_of": "20260430"
    }
  ],
  "limitations": ["缺失或降级说明"]
}
```
