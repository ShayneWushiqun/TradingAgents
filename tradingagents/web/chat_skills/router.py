from __future__ import annotations

from .base import ChatSkill
from .external_data import ExternalDataSkill
from .news_search import NewsSearchSkill
from .report_context import ReportContextSkill
from .tushare_data import TushareDataSkill


TUSHARE_KEYWORDS = (
    "资金流",
    "moneyflow",
    "pe",
    "pb",
    "估值",
    "市盈率",
    "市净率",
    "成交额",
    "成交量",
    "行情",
    "收盘",
    "涨跌幅",
)

NEWS_KEYWORDS = (
    "新闻",
    "公告",
    "利空",
    "利好",
    "消息",
    "事件",
    "政策",
    "监管",
    "舆情",
    "传闻",
)

EXTERNAL_DATA_KEYWORDS = (
    "外部数据",
    "实时数据",
    "实时行情",
    "tool",
    "tools",
    "工具",
    "数据源",
    "tushare",
    "akshare",
    "tavily",
    "腾讯财经",
    "腾讯",
)


class ChatSkillRouter:
    def __init__(
        self,
        report_skill: ChatSkill | None = None,
        tushare_skill: ChatSkill | None = None,
        news_skill: ChatSkill | None = None,
        external_data_skill: ChatSkill | None = None,
    ) -> None:
        self.report_skill = report_skill or ReportContextSkill()
        self.tushare_skill = tushare_skill or TushareDataSkill()
        self.news_skill = news_skill or NewsSearchSkill()
        self.external_data_skill = external_data_skill or ExternalDataSkill()

    def select(self, message: str, smart_search: bool = False) -> ChatSkill:
        normalized = message.lower()
        if smart_search:
            return self.external_data_skill
        if any(keyword in normalized for keyword in EXTERNAL_DATA_KEYWORDS):
            return self.external_data_skill
        if any(keyword in normalized for keyword in NEWS_KEYWORDS):
            return self.news_skill
        if any(keyword in normalized for keyword in TUSHARE_KEYWORDS):
            return self.tushare_skill
        return self.report_skill
