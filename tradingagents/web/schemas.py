from pydantic import BaseModel, Field, field_validator


class AnalysisRequest(BaseModel):
    ts_code: str
    trade_date: str
    analysts: list[str] = Field(default_factory=lambda: ["market", "fundamentals"])
    research_depth: int = 1
    llm_provider: str = "deepseek"
    quick_model: str = "deepseek-v4-flash"
    deep_model: str = "deepseek-v4-flash"
    force_refresh: bool = False

    @field_validator("ts_code")
    @classmethod
    def validate_a_share_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized.isdigit() and len(normalized) == 6:
            if normalized.startswith(("600", "601", "603", "605", "688", "689")):
                normalized = f"{normalized}.SH"
            elif normalized.startswith(("000", "001", "002", "003", "300", "301")):
                normalized = f"{normalized}.SZ"
            elif normalized.startswith(("430", "8", "9")):
                normalized = f"{normalized}.BJ"
        if not normalized.endswith((".SH", ".SZ", ".BJ")):
            raise ValueError("ts_code must end with .SH, .SZ, or .BJ")
        return normalized


class ChatRequest(BaseModel):
    task_id: str = ""
    message: str
    expert_mode: bool = False
    smart_search: bool = False
    conversation_history: list[dict[str, str]] = Field(default_factory=list)


class HotRadarRunRequest(BaseModel):
    trade_date: str
    batch_time: str = "daily"
    top_n: int = 20

    @field_validator("batch_time")
    @classmethod
    def validate_batch_time(cls, value: str) -> str:
        if value != "daily":
            raise ValueError("batch_time must be daily")
        return value

    @field_validator("top_n")
    @classmethod
    def validate_top_n(cls, value: int) -> int:
        if value not in {10, 20, 30, 40, 50}:
            raise ValueError("top_n must be 10, 20, 30, 40, or 50")
        return value


class HotRadarFetchRequest(BaseModel):
    """Force (or optionally soft) sync of ths_hot snapshot."""

    trade_date: str
    batch_time: str = "daily"
    top_n: int = 20
    force_refresh: bool = True

    @field_validator("batch_time")
    @classmethod
    def validate_batch_time(cls, value: str) -> str:
        if value != "daily":
            raise ValueError("batch_time must be daily")
        return value

    @field_validator("top_n")
    @classmethod
    def validate_top_n(cls, value: int) -> int:
        if value not in {10, 20, 30, 40, 50}:
            raise ValueError("top_n must be 10, 20, 30, 40, or 50")
        return value
