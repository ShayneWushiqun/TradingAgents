from pydantic import BaseModel, Field, field_validator


class AnalysisRequest(BaseModel):
    ts_code: str
    trade_date: str
    analysts: list[str] = Field(default_factory=lambda: ["market", "fundamentals"])
    research_depth: int = 1
    llm_provider: str = "deepseek"
    quick_model: str = "deepseek-chat"
    deep_model: str = "deepseek-chat"

    @field_validator("ts_code")
    @classmethod
    def validate_a_share_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized.endswith((".SH", ".SZ", ".BJ")):
            raise ValueError("ts_code must end with .SH, .SZ, or .BJ")
        return normalized


class ChatRequest(BaseModel):
    task_id: str
    message: str
