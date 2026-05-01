from tradingagents.default_config import DEFAULT_CONFIG

from .schemas import AnalysisRequest
from .tasks import AnalysisTask, TaskRegistry


class AnalysisService:
    def __init__(self, registry: TaskRegistry) -> None:
        self.registry = registry

    def create_task(self, request: AnalysisRequest) -> AnalysisTask:
        return self.registry.create(request)

    def build_config(self, request: AnalysisRequest) -> dict:
        config = DEFAULT_CONFIG.copy()
        config["data_vendors"] = {
            "core_stock_apis": "tushare",
            "technical_indicators": "tushare",
            "fundamental_data": "tushare",
            "news_data": "tushare",
        }
        config["llm_provider"] = request.llm_provider
        config["quick_think_llm"] = request.quick_model
        config["deep_think_llm"] = request.deep_model
        config["max_debate_rounds"] = request.research_depth
        config["max_risk_discuss_rounds"] = request.research_depth
        config["output_language"] = "Chinese"
        return config
