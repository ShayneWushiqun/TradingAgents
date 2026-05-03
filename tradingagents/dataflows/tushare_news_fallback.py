def get_news(ticker: str, start_date: str, end_date: str) -> str:
    return (
        f"## Tushare Fallback News Context for {ticker}\n"
        f"AKShare 与 Tavily 未返回可用新闻，时间范围：{start_date} 至 {end_date}。\n"
        "请将本次新闻分析降级为 Tushare 已有的基本面、财务指标、日线行情和 moneyflow 资金流说明：\n"
        "- 若资金持续流入且财务质量稳定，可视为弱正面情绪代理。\n"
        "- 若资金流出、估值承压或财务指标走弱，应在新闻结论中标记为风险偏高。\n"
        "- 明确提示：本段不包含外部新闻或社交媒体原文。"
    )


def get_global_news(curr_date: str, look_back_days: int = 7, limit: int = 5) -> str:
    return (
        f"## Tushare Fallback Market Context 截至 {curr_date}\n"
        "AKShare 与 Tavily 未返回可用市场新闻。\n"
        "请结合 Tushare 行情、估值、财务和 moneyflow 数据进行弱新闻环境判断，"
        "并在报告中说明外部新闻源当前不可用。"
    )
