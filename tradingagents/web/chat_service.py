from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.web.chat_skills import ChatSkillRouter, SkillContext, SkillResult
from tradingagents.web.tasks import AnalysisTask, TaskRegistry


class ChatLLMUnavailable(RuntimeError):
    """Raised when the chat LLM cannot be used and deterministic fallback is needed."""


class ChatLLM(Protocol):
    provider: str

    def answer(
        self,
        *,
        task: AnalysisTask,
        message: str,
        skill_result: SkillResult,
        expert_mode: bool = False,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        """Generate a natural-language answer from the selected skill context."""


class DeepSeekChatLLM:
    provider = "deepseek"
    default_model = "deepseek-v4-flash"
    expert_model = "deepseek-v4-pro"

    def __init__(
        self,
        default_model: str = "deepseek-v4-flash",
        expert_model: str = "deepseek-v4-pro",
    ) -> None:
        self.default_model = default_model
        self.expert_model = expert_model
        self._llms = {}

    def model_for(self, expert_mode: bool = False) -> str:
        return self.expert_model if expert_mode else self.default_model

    def answer(
        self,
        *,
        task: AnalysisTask,
        message: str,
        skill_result: SkillResult,
        expert_mode: bool = False,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key or api_key == "placeholder":
            raise ChatLLMUnavailable("DEEPSEEK_API_KEY is not configured")

        llm = self._get_llm(self.model_for(expert_mode))
        response = llm.invoke(
            _build_deepseek_messages(
                task,
                message,
                skill_result,
                conversation_history=conversation_history,
            )
        )
        content = getattr(response, "content", response)
        text = str(content).strip()
        if not text:
            raise ChatLLMUnavailable("DeepSeek returned an empty answer")
        return text

    def stream_answer(
        self,
        *,
        task: AnalysisTask,
        message: str,
        skill_result: SkillResult,
        expert_mode: bool = False,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key or api_key == "placeholder":
            raise ChatLLMUnavailable("DEEPSEEK_API_KEY is not configured")

        llm = self._get_llm(self.model_for(expert_mode))
        messages = _build_deepseek_messages(
            task,
            message,
            skill_result,
            conversation_history=conversation_history,
        )
        stream = getattr(llm, "stream", None)
        if not callable(stream):
            yield from _chunk_text(self.answer(
                task=task,
                message=message,
                skill_result=skill_result,
                expert_mode=expert_mode,
                conversation_history=conversation_history,
            ))
            return

        emitted = False
        for chunk in stream(messages):
            content = getattr(chunk, "content", chunk)
            text = _content_to_text(content)
            if text:
                emitted = True
                yield text
        if not emitted:
            raise ChatLLMUnavailable("DeepSeek returned an empty stream")

    def _get_llm(self, model: str):
        if model not in self._llms:
            self._llms[model] = create_llm_client(self.provider, model).get_llm()
        return self._llms[model]


class TaskProvider(Protocol):
    def get_task(self, task_id: str) -> AnalysisTask | None:
        """Return a task by id."""

    def latest_task(self) -> AnalysisTask | None:
        """Return the latest task."""


class RegistryTaskProvider:
    def __init__(self, registry: TaskRegistry) -> None:
        self.registry = registry

    def get_task(self, task_id: str) -> AnalysisTask | None:
        return self.registry.get(task_id)

    def latest_task(self) -> AnalysisTask | None:
        return self.registry.latest()


class ChatService:
    def __init__(
        self,
        task_provider: TaskProvider | TaskRegistry,
        router: ChatSkillRouter | None = None,
        chat_llm: ChatLLM | None = None,
    ) -> None:
        if isinstance(task_provider, TaskRegistry):
            task_provider = RegistryTaskProvider(task_provider)
        self.task_provider = task_provider
        self.router = router or ChatSkillRouter()
        self.chat_llm = chat_llm or DeepSeekChatLLM()

    def reply(
        self,
        task_id: str | None,
        message: str,
        expert_mode: bool = False,
        smart_search: bool = False,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        payload = self.reply_payload(
            task_id,
            message,
            expert_mode=expert_mode,
            smart_search=smart_search,
            conversation_history=conversation_history,
        )
        return str(payload["reply"])

    def reply_payload(
        self,
        task_id: str | None,
        message: str,
        expert_mode: bool = False,
        smart_search: bool = False,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        task = self._resolve_task(task_id)
        if task is None:
            fallback = SkillResult(
                skill="none",
                status="unavailable",
                conclusion=(
                    "未找到可用分析任务，请先在工作台完成一次单股分析后再追问。"
                ),
                evidence=[
                    "当前请求没有匹配的 task_id，也没有可恢复的 latest analysis。"
                ],
                data_sources=["report_context"],
                limitations=["Agent Chat 需要至少一个分析任务作为上下文。"],
            )
            return {
                "reply": fallback.render(),
                "sections": fallback.as_sections(),
                "task_id": None,
                "ts_code": None,
                "trade_date": None,
                "task_status": None,
            }

        skill = self.router.select(message, smart_search=smart_search)
        result = skill.run(SkillContext(task=task, message=message))
        llm_provider = getattr(self.chat_llm, "provider", "deepseek")
        llm_model = _model_for_chat_llm(self.chat_llm, expert_mode)
        llm_used = False

        try:
            llm_answer = self.chat_llm.answer(
                task=task,
                message=message,
                skill_result=result,
                expert_mode=expert_mode,
                conversation_history=conversation_history or [],
            )
        except ChatLLMUnavailable as exc:
            result.limitations.append(
                f"DeepSeek 未启用或不可用，当前回答由 {result.skill} 规则降级生成：{_safe_error(exc)}。"
            )
        except Exception as exc:
            result.limitations.append(
                f"DeepSeek 调用失败，当前回答由 {result.skill} 规则降级生成：{_safe_error(exc)}。"
            )
        else:
            result.conclusion = llm_answer
            llm_used = True
            if llm_provider not in result.data_sources:
                result.data_sources.append(llm_provider)

        sections = result.as_sections()
        sections["llm_provider"] = llm_provider
        sections["llm_model"] = llm_model
        sections["expert_mode"] = expert_mode
        sections["smart_search"] = smart_search
        sections["history_messages"] = len(conversation_history or [])
        sections["context_compressed"] = _history_would_compress(conversation_history or [])
        sections["llm_used"] = llm_used
        return {
            "reply": result.render(),
            "sections": sections,
            "task_id": task.task_id,
            "ts_code": task.request.ts_code,
            "trade_date": task.request.trade_date,
            "task_status": task.status,
        }

    def stream_reply_events(
        self,
        task_id: str | None,
        message: str,
        expert_mode: bool = False,
        smart_search: bool = False,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> Iterator[dict[str, Any]]:
        task = self._resolve_task(task_id)
        if task is None:
            fallback = SkillResult(
                skill="none",
                status="unavailable",
                conclusion=(
                    "未找到可用分析任务，请先在工作台完成一次单股分析后再追问。"
                ),
                evidence=[
                    "当前请求没有匹配的 task_id，也没有可恢复的 latest analysis。"
                ],
                data_sources=["report_context"],
                limitations=["Agent Chat 需要至少一个分析任务作为上下文。"],
            )
            yield {
                "event": "completed",
                "data": {
                    "reply": fallback.render(),
                    "sections": fallback.as_sections(),
                    "task_id": None,
                    "ts_code": None,
                    "trade_date": None,
                    "task_status": None,
                    "history_messages": 0,
                    "context_compressed": False,
                },
            }
            return

        skill = self.router.select(message, smart_search=smart_search)
        yield {
            "event": "tool_started",
            "data": {
                "label": "智能搜索：选择外部数据工具" if smart_search else "正在选择工具",
                "skill": skill.name,
                "ts_code": task.request.ts_code,
                "trade_date": task.request.trade_date,
                "smart_search": smart_search,
            },
        }

        result = skill.run(SkillContext(task=task, message=message))
        yield {
            "event": "tool_completed",
            "data": {
                "label": "工具已返回上下文",
                "skill": result.skill,
                "status": result.status,
                "evidence_count": len(result.evidence),
                "data_sources": list(result.data_sources),
                "smart_search": smart_search,
            },
        }

        llm_provider = getattr(self.chat_llm, "provider", "deepseek")
        llm_model = _model_for_chat_llm(self.chat_llm, expert_mode)
        yield {
            "event": "llm_started",
            "data": {
                "label": "正在调用 DeepSeek 模型",
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "expert_mode": expert_mode,
                "smart_search": smart_search,
            },
        }

        answer_chunks: list[str] = []
        llm_used = False
        try:
            stream_answer = getattr(self.chat_llm, "stream_answer", None)
            if callable(stream_answer):
                chunk_iterable = stream_answer(
                    task=task,
                    message=message,
                    skill_result=result,
                    expert_mode=expert_mode,
                    conversation_history=conversation_history or [],
                )
            else:
                chunk_iterable = _chunk_text(
                    self.chat_llm.answer(
                        task=task,
                        message=message,
                        skill_result=result,
                        expert_mode=expert_mode,
                        conversation_history=conversation_history or [],
                    )
                )

            for chunk in chunk_iterable:
                text = str(chunk)
                if not text:
                    continue
                answer_chunks.append(text)
                yield {"event": "answer_delta", "data": {"delta": text}}
            if answer_chunks:
                result.conclusion = "".join(answer_chunks).strip()
                llm_used = True
                if llm_provider not in result.data_sources:
                    result.data_sources.append(llm_provider)
        except ChatLLMUnavailable as exc:
            result.limitations.append(
                f"DeepSeek 未启用或不可用，当前回答由 {result.skill} 规则降级生成：{_safe_error(exc)}。"
            )
        except Exception as exc:
            result.limitations.append(
                f"DeepSeek 调用失败，当前回答由 {result.skill} 规则降级生成：{_safe_error(exc)}。"
            )

        if not answer_chunks:
            for chunk in _chunk_text(result.conclusion):
                yield {"event": "answer_delta", "data": {"delta": chunk}}

        sections = result.as_sections()
        sections["llm_provider"] = llm_provider
        sections["llm_model"] = llm_model
        sections["expert_mode"] = expert_mode
        sections["smart_search"] = smart_search
        sections["history_messages"] = len(conversation_history or [])
        sections["context_compressed"] = _history_would_compress(conversation_history or [])
        sections["llm_used"] = llm_used
        yield {
            "event": "completed",
            "data": {
                "reply": result.render(),
                "sections": sections,
                "task_id": task.task_id,
                "ts_code": task.request.ts_code,
                "trade_date": task.request.trade_date,
                "task_status": task.status,
            },
        }

    def _resolve_task(self, task_id: str | None) -> AnalysisTask | None:
        normalized = (task_id or "").strip()
        if normalized:
            task = self.task_provider.get_task(normalized)
            if task is not None:
                return task
        return self.task_provider.latest_task()


def _build_deepseek_messages(
    task: AnalysisTask,
    message: str,
    skill_result: SkillResult,
    conversation_history: list[dict[str, str]] | None = None,
) -> list:
    sections = task.report_sections or {}
    final_decision = task.final_decision or sections.get("final_trade_decision", "")
    report_context = _compact_report_sections(
        {
            "final_trade_decision": final_decision,
            "market_report": sections.get("market_report", ""),
            "fundamentals_report": sections.get("fundamentals_report", ""),
            "news_report": sections.get("news_report", ""),
            "sentiment_report": sections.get("sentiment_report", ""),
            "trader_investment_plan": sections.get("trader_investment_plan", ""),
        }
    )
    skill_context = skill_result.as_sections()
    conversation_context, context_compressed = _compact_conversation_history(
        conversation_history or []
    )
    smart_search_instruction = ""
    if skill_context["skill"] == "external_data_tools":
        smart_search_instruction = (
            "当前已启用智能搜索/外部数据工具。请优先综合已返回的 Tushare、腾讯财经、"
            "AKShare、Tavily 证据；明确说明哪些数据源成功、哪些降级；"
            "不要声称未接入外部数据，除非 data_sources 只有 report_context。"
        )

    return [
        SystemMessage(
            content=(
                "你是 A 股投研 Agent Chat，负责基于 TradingAgents 报告和工具数据回答用户追问。"
                "必须直接回答用户当前问题，不要只复述报告摘要。"
                "如果证据不足，要说明需要观察什么数据。"
                "不要编造实时行情、公告或新闻；不要给保证性收益承诺。"
                "用中文回答，适合个人投研复盘阅读。"
                f"{smart_search_instruction}"
            )
        ),
        HumanMessage(
            content=(
                f"股票：{task.request.ts_code}\n"
                f"交易日：{task.request.trade_date}\n"
                f"任务状态：{task.status}\n"
                f"用户问题：{message}\n\n"
                "已选工具/上下文：\n"
                f"- skill: {skill_context['skill']}\n"
                f"- status: {skill_context['status']}\n"
                f"- evidence: {' | '.join(skill_context['evidence'])}\n"
                f"- data_sources: {', '.join(skill_context['data_sources'])}\n"
                f"- limitations: {' | '.join(skill_context['limitations'])}\n\n"
                "对话历史上下文：\n"
                f"{conversation_context or '暂无历史对话。'}\n"
                f"history_compressed: {context_compressed}\n\n"
                "TradingAgents 报告上下文：\n"
                f"{report_context}\n\n"
                "请给出：1）直接结论；2）关键依据；3）接下来观察什么；"
                "控制在 4-8 句话，围绕用户问题回答。"
            )
        ),
    ]


def _compact_report_sections(sections: dict[str, str], limit: int = 7000) -> str:
    chunks: list[str] = []
    for key, value in sections.items():
        compact = " ".join(str(value or "").split())
        if compact:
            chunks.append(f"[{key}] {compact}")
    text = "\n".join(chunks)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def _safe_error(exc: Exception) -> str:
    message = str(exc).strip()
    if not message or "/" in message or "\\" in message:
        return type(exc).__name__
    return message


def _history_would_compress(history: list[dict[str, str]]) -> bool:
    _text, compressed = _compact_conversation_history(history)
    return compressed


def _compact_conversation_history(
    history: list[dict[str, str]],
    limit: int = 4000,
    keep_recent: int = 8,
) -> tuple[str, bool]:
    cleaned: list[tuple[str, str]] = []
    for item in history:
        role = str(item.get("role") or "user")[:24]
        content = " ".join(str(item.get("content") or "").split())
        if content:
            cleaned.append((role, content))

    if not cleaned:
        return "", False

    full = "\n".join(f"{role}: {content}" for role, content in cleaned)
    if len(full) <= limit and len(cleaned) <= keep_recent:
        return full, False

    recent = cleaned[-keep_recent:]
    older = cleaned[:-keep_recent]
    older_text = " ".join(content for _role, content in older)
    summary_limit = max(400, limit // 3)
    older_summary = older_text[:summary_limit]
    if len(older_text) > summary_limit:
        older_summary += "..."

    recent_text = "\n".join(f"{role}: {content}" for role, content in recent)
    header = "早期对话压缩摘要："
    recent_header = "\n\n最近对话：\n"
    available_for_body = max(200, limit - len(header) - len(recent_header))
    recent_budget = max(120, available_for_body // 2)
    summary_budget = max(80, available_for_body - recent_budget)
    if len(older_summary) > summary_budget:
        older_summary = older_summary[: summary_budget - 3] + "..."
    if len(recent_text) > recent_budget:
        recent_text = recent_text[-recent_budget:]
    compacted = f"{header}{older_summary}{recent_header}{recent_text}"
    return compacted, True


def _chunk_text(text: str, size: int = 18) -> Iterator[str]:
    compact = str(text or "")
    if not compact:
        return
    for start in range(0, len(compact), size):
        yield compact[start : start + size]


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for item in content:
            if isinstance(item, dict):
                pieces.append(str(item.get("text") or item.get("content") or ""))
            else:
                pieces.append(str(item))
        return "".join(pieces)
    return str(content)


def _model_for_chat_llm(chat_llm: ChatLLM, expert_mode: bool) -> str:
    model_for = getattr(chat_llm, "model_for", None)
    if callable(model_for):
        return str(model_for(expert_mode))
    return "deepseek-v4-flash"
