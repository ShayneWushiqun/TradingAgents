# A股新闻搜索 Skill

## 触发场景

- 用户追问公司近期新闻、公告、监管事件、行业政策或市场传闻。
- 当前报告中的 news 或 sentiment 结论需要更新到更近时间。
- 用户要求解释股价异动背后的新闻催化、公告影响或外部事件。
- 用户明确要求联网搜索、核验来源或补充报告之外的信息。

## 输入参数

- `ts_code`: A 股证券代码，优先使用标准后缀。
- `name`: 公司简称或关键词，用于新闻和公告搜索。
- `trade_date`: 当前分析交易日，用于限定“截至该日”的回答。
- `start_date`: 新闻搜索起始日期。
- `end_date`: 新闻搜索结束日期。
- `keywords`: 可选关键词，例如 “业绩预告”、“减持”、“订单”、“监管函”。
- `max_results`: 返回条数上限，默认 5 至 10 条。
- `question`: 用户原始问题，用于判断是否需要公告、新闻或网页搜索。
- `task_id`: 可选分析任务 ID，用于读取已有报告上下文。

## 可调用数据源

- AKShare A 股新闻、公告、研报或市场资讯相关接口。
- Tavily Search 公开网页搜索。
- Tushare Pro 公告、业绩预告和公司行动相关接口。
- 当前 TradingAgents 报告上下文，包括 news、sentiment 和 final decision。

## 6000+ Tushare 积分下默认允许的接口

- `stock_basic`: 获取公司简称和标准代码，辅助检索。
- `trade_cal`: 规范交易日范围。
- `forecast`: 业绩预告。
- `express`: 业绩快报。
- `dividend`: 分红送股。
- `income`: 利润表，用于核验新闻中的业绩表述。
- `fina_indicator`: 财务指标，用于核验公告影响。
- `stk_holdernumber`: 股东人数，用于辅助解释筹码变化。
- `daily`: 新闻事件前后行情复核。
- `daily_basic`: 事件前后估值和成交指标复核。

## 需要额外权限时如何降级

- AKShare 新闻或公告不可用时，先使用 Tavily Search 检索公开来源，并标注来源类型为网页搜索。
- Tavily 不可用时，回退到当前报告中的 news、sentiment 和 fundamentals 内容，只回答已有证据支持的部分。
- Tushare 权限不足时，用已允许的行情和财务接口做事件前后复核，不编造公告原文。
- 搜索结果互相冲突时，优先使用交易所公告、公司公告和主流财经媒体，并在回答中列出冲突点。
- 无法确认发布时间或来源可信度时，将结论标记为“待核验”，避免给出确定性交易建议。
- 不输出或记录任何 token、环境变量值或鉴权细节。

## 返回格式

```json
{
  "skill": "a_share_news_search",
  "status": "ok | partial | unavailable",
  "data_sources": ["akshare", "tavily", "tushare", "report_context"],
  "query": {
    "ts_code": "600519.SH",
    "keywords": ["业绩", "公告"],
    "date_range": ["20260401", "20260430"]
  },
  "summary": "新闻和公告对当前问题的综合回答。",
  "items": [
    {
      "title": "新闻或公告标题",
      "source": "来源名称",
      "published_at": "发布时间",
      "url": "可选链接",
      "relevance": "和用户问题的关系"
    }
  ],
  "impact": "对报告结论、风险或交易计划的影响。",
  "limitations": ["缺失、冲突或降级说明"]
}
```
