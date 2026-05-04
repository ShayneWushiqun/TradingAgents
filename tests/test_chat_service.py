import pytest

from tradingagents.web.chat_service import ChatService, _compact_conversation_history
from tradingagents.web.chat_skills import ChatSkillRouter, SkillResult
from tradingagents.web.schemas import AnalysisRequest
from tradingagents.web.tasks import TaskRegistry


class RecordingSkill:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    def run(self, context):
        self.calls.append(self.name)
        return SkillResult(
            skill=self.name,
            conclusion=f"{self.name} handled {context.ts_code}",
            evidence=[context.message],
            data_sources=[self.name],
            limitations=["test limitation"],
        )


class FakeChatLLM:
    provider = "deepseek"

    def __init__(
        self,
        response: str = "LLM 结合 600519.SH 的上下文生成的个性化回答",
    ) -> None:
        self.response = response
        self.calls = []

    def model_for(self, expert_mode: bool = False) -> str:
        return "deepseek-v4-pro" if expert_mode else "deepseek-v4-flash"

    def answer(self, *, task, message, skill_result, expert_mode=False, conversation_history=None):
        self.calls.append(
            {
                "ts_code": task.request.ts_code,
                "message": message,
                "skill": skill_result.skill,
                "evidence": list(skill_result.evidence),
                "expert_mode": expert_mode,
                "conversation_history": conversation_history,
            }
        )
        return self.response


class StreamingFakeChatLLM(FakeChatLLM):
    def stream_answer(self, *, task, message, skill_result, expert_mode=False, conversation_history=None):
        self.calls.append(
            {
                "ts_code": task.request.ts_code,
                "message": message,
                "skill": skill_result.skill,
                "evidence": list(skill_result.evidence),
                "expert_mode": expert_mode,
                "conversation_history": conversation_history,
            }
        )
        yield "第一段"
        yield "第二段"


def _registry_with_task() -> tuple[TaskRegistry, str]:
    registry = TaskRegistry()
    task = registry.create(
        AnalysisRequest(ts_code="600519.SH", trade_date="2026-04-30")
    )
    task.status = "completed"
    task.report_sections["final_trade_decision"] = "Rating: Hold\n等待。"
    task.final_decision = task.report_sections["final_trade_decision"]
    return registry, task.task_id


def _service_with_recording_router(registry: TaskRegistry, calls: list[str]) -> ChatService:
    router = ChatSkillRouter(
        report_skill=RecordingSkill("report_context", calls),
        tushare_skill=RecordingSkill("tushare_a_share_data", calls),
        news_skill=RecordingSkill("a_share_news_search", calls),
        external_data_skill=RecordingSkill("external_data_tools", calls),
    )
    return ChatService(registry, router=router, chat_llm=FakeChatLLM())


@pytest.mark.unit
def test_chat_service_routes_moneyflow_and_valuation_to_tushare_skill():
    registry, task_id = _registry_with_task()
    calls: list[str] = []
    service = _service_with_recording_router(registry, calls)

    reply = service.reply(task_id, "资金流和 PE 估值怎么看？")

    assert calls == ["tushare_a_share_data"]
    assert "结论：" in reply
    assert "数据来源：" in reply
    assert "限制/降级说明：" in reply


@pytest.mark.unit
def test_chat_service_routes_news_questions_to_news_skill():
    registry, task_id = _registry_with_task()
    calls: list[str] = []
    service = _service_with_recording_router(registry, calls)

    service.reply(task_id, "公告有没有利空？")

    assert calls == ["a_share_news_search"]


@pytest.mark.unit
def test_chat_service_routes_smart_search_to_external_data_skill():
    registry, task_id = _registry_with_task()
    calls: list[str] = []
    service = _service_with_recording_router(registry, calls)

    payload = service.reply_payload(
        task_id,
        "现在华工科技有什么新消息需要验证？",
        smart_search=True,
    )

    assert calls == ["external_data_tools"]
    assert payload["sections"]["skill"] == "external_data_tools"
    assert payload["sections"]["smart_search"] is True


@pytest.mark.unit
def test_chat_service_routes_normal_follow_up_to_report_context():
    registry, task_id = _registry_with_task()
    calls: list[str] = []
    service = _service_with_recording_router(registry, calls)

    service.reply(task_id, "这个交易计划是否保守？")

    assert calls == ["report_context"]


@pytest.mark.unit
def test_chat_service_uses_latest_task_when_task_id_missing():
    registry, _task_id = _registry_with_task()
    calls: list[str] = []
    service = _service_with_recording_router(registry, calls)

    reply = service.reply("", "普通追问")

    assert calls == ["report_context"]
    assert "600519.SH" in reply


@pytest.mark.unit
def test_chat_service_uses_latest_task_when_task_id_not_found():
    registry, _task_id = _registry_with_task()
    calls: list[str] = []
    service = _service_with_recording_router(registry, calls)

    reply = service.reply("missing-task", "新闻如何？")

    assert calls == ["a_share_news_search"]
    assert "结论：" in reply


@pytest.mark.unit
def test_chat_service_returns_clear_prompt_when_no_task_exists():
    service = ChatService(TaskRegistry())

    reply = service.reply("", "怎么看？")

    assert "未找到可用分析任务" in reply
    assert "latest analysis" in reply
    assert "Agent Chat 需要至少一个分析任务" in reply


@pytest.mark.unit
def test_chat_service_uses_llm_to_answer_from_skill_context():
    registry, task_id = _registry_with_task()
    calls: list[str] = []
    llm = FakeChatLLM("华工科技上涨空间需要结合催化兑现和止损位判断。")
    router = ChatSkillRouter(
        report_skill=RecordingSkill("report_context", calls),
        tushare_skill=RecordingSkill("tushare_a_share_data", calls),
        news_skill=RecordingSkill("a_share_news_search", calls),
        external_data_skill=RecordingSkill("external_data_tools", calls),
    )
    service = ChatService(registry, router=router, chat_llm=llm)

    payload = service.reply_payload(task_id, "当前华工科技还有上涨的空间吗？")

    assert calls == ["report_context"]
    assert llm.calls == [
        {
            "ts_code": "600519.SH",
            "message": "当前华工科技还有上涨的空间吗？",
            "skill": "report_context",
            "evidence": ["当前华工科技还有上涨的空间吗？"],
            "expert_mode": False,
            "conversation_history": [],
        }
    ]
    assert payload["sections"]["conclusion"] == "华工科技上涨空间需要结合催化兑现和止损位判断。"
    assert payload["sections"]["llm_provider"] == "deepseek"
    assert payload["sections"]["llm_model"] == "deepseek-v4-flash"
    assert payload["sections"]["expert_mode"] is False
    assert payload["sections"]["data_sources"] == ["report_context", "deepseek"]


@pytest.mark.unit
def test_chat_service_uses_deepseek_v4_pro_in_expert_mode():
    registry, task_id = _registry_with_task()
    calls: list[str] = []
    llm = FakeChatLLM("专家模式使用更强模型回答。")
    router = ChatSkillRouter(
        report_skill=RecordingSkill("report_context", calls),
        tushare_skill=RecordingSkill("tushare_a_share_data", calls),
        news_skill=RecordingSkill("a_share_news_search", calls),
        external_data_skill=RecordingSkill("external_data_tools", calls),
    )
    service = ChatService(registry, router=router, chat_llm=llm)

    payload = service.reply_payload(task_id, "做一次专家级复盘", expert_mode=True)

    assert llm.calls[0]["expert_mode"] is True
    assert payload["sections"]["llm_model"] == "deepseek-v4-pro"
    assert payload["sections"]["expert_mode"] is True


@pytest.mark.unit
def test_chat_service_accepts_conversation_history_and_reports_compression():
    registry, task_id = _registry_with_task()
    calls: list[str] = []
    llm = FakeChatLLM("结合历史追问回答。")
    router = ChatSkillRouter(
        report_skill=RecordingSkill("report_context", calls),
        tushare_skill=RecordingSkill("tushare_a_share_data", calls),
        news_skill=RecordingSkill("a_share_news_search", calls),
        external_data_skill=RecordingSkill("external_data_tools", calls),
    )
    service = ChatService(registry, router=router, chat_llm=llm)
    history = [
        {"role": "user", "content": f"第 {index} 轮问题 " + "很长" * 120}
        for index in range(18)
    ]

    payload = service.reply_payload(task_id, "继续分析", conversation_history=history)

    assert llm.calls[0]["conversation_history"] == history
    assert payload["sections"]["context_compressed"] is True
    assert payload["sections"]["history_messages"] == 18


@pytest.mark.unit
def test_compact_conversation_history_keeps_recent_turns_and_summarizes_older_context():
    history = [
        {"role": "user", "content": f"早期问题 {index} " + "x" * 200}
        for index in range(14)
    ]

    compacted, was_compressed = _compact_conversation_history(history, limit=600, keep_recent=4)

    assert was_compressed is True
    assert "早期对话压缩摘要" in compacted
    assert "最近对话" in compacted
    assert "早期问题 13" in compacted
    assert "早期问题 0" in compacted


@pytest.mark.unit
def test_chat_service_streams_tool_and_llm_events():
    registry, task_id = _registry_with_task()
    calls: list[str] = []
    llm = StreamingFakeChatLLM()
    router = ChatSkillRouter(
        report_skill=RecordingSkill("report_context", calls),
        tushare_skill=RecordingSkill("tushare_a_share_data", calls),
        news_skill=RecordingSkill("a_share_news_search", calls),
        external_data_skill=RecordingSkill("external_data_tools", calls),
    )
    service = ChatService(registry, router=router, chat_llm=llm)

    events = list(
        service.stream_reply_events(
            task_id,
            "当前华工科技还有上涨预期吗？",
            expert_mode=True,
            smart_search=True,
        )
    )

    assert [event["event"] for event in events] == [
        "tool_started",
        "tool_completed",
        "llm_started",
        "answer_delta",
        "answer_delta",
        "completed",
    ]
    assert events[0]["data"]["skill"] == "external_data_tools"
    assert events[1]["data"]["data_sources"] == ["external_data_tools"]
    assert events[2]["data"]["llm_model"] == "deepseek-v4-pro"
    assert events[2]["data"]["smart_search"] is True
    assert events[3]["data"]["delta"] == "第一段"
    assert events[4]["data"]["delta"] == "第二段"
    assert events[-1]["data"]["sections"]["conclusion"] == "第一段第二段"
    assert events[-1]["data"]["sections"]["llm_used"] is True
    assert events[-1]["data"]["sections"]["expert_mode"] is True
    assert events[-1]["data"]["sections"]["smart_search"] is True
