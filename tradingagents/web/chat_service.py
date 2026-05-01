from .tasks import TaskRegistry


class ChatService:
    def __init__(self, registry: TaskRegistry) -> None:
        self.registry = registry

    def reply(self, task_id: str, message: str) -> str:
        task = self.registry.get(task_id)
        if task is None:
            return "未找到对应分析任务，请先运行一次单股分析。"

        return (
            f"基于 {task.request.ts_code} 在 {task.request.trade_date} 的 TradingAgents 报告，"
            "我会先检查趋势、估值、财务质量和 moneyflow。"
            f"你的问题是：{message}"
        )
