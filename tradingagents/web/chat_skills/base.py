from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from tradingagents.web.tasks import AnalysisTask


@dataclass(frozen=True)
class SkillContext:
    task: AnalysisTask
    message: str

    @property
    def ts_code(self) -> str:
        return self.task.request.ts_code

    @property
    def trade_date(self) -> str:
        return self.task.request.trade_date

    @property
    def report_sections(self) -> dict[str, str]:
        return self.task.report_sections


@dataclass
class SkillResult:
    skill: str
    conclusion: str
    evidence: list[str] = field(default_factory=list)
    data_sources: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    status: str = "ok"

    def as_sections(self) -> dict[str, Any]:
        evidence = self.evidence if self.evidence else ["当前没有可展示的额外证据。"]
        sources = self.data_sources if self.data_sources else ["report_context"]
        limits = self.limitations if self.limitations else ["无额外限制。"]
        return {
            "skill": self.skill,
            "status": self.status,
            "conclusion": self.conclusion,
            "evidence": list(evidence),
            "data_sources": list(sources),
            "limitations": list(limits),
        }

    def render(self) -> str:
        evidence = self.evidence or ["当前没有可展示的额外证据。"]
        sources = self.data_sources or ["report_context"]
        limitations = self.limitations or ["无额外限制。"]
        return (
            f"结论：{self.conclusion}\n\n"
            "证据：\n"
            + "\n".join(f"- {item}" for item in evidence)
            + "\n\n数据来源：\n"
            + "\n".join(f"- {source}" for source in sources)
            + "\n\n限制/降级说明：\n"
            + "\n".join(f"- {item}" for item in limitations)
        )


class ChatSkill(Protocol):
    name: str

    def run(self, context: SkillContext) -> SkillResult:
        """Run the skill and return a structured chat answer."""
