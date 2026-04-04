import os

_provider = os.getenv("PRIMARY_PROVIDER", "openai").lower()

_PROVIDER_DEFAULTS = {
    "openai": {
        "deep_think_llm": "gpt-5.4",
        "quick_think_llm": "gpt-5.4-mini",
        "backend_url": "https://api.openai.com/v1",
    },
    "openai_compatible": {
        "deep_think_llm": os.getenv("OPENAI_COMPATIBLE_MODEL_ID", "gpt-4"),
        "quick_think_llm": os.getenv("OPENAI_COMPATIBLE_MODEL_ID", "gpt-4"),
        "backend_url": os.getenv("OPENAI_COMPATIBLE_BASE_URL", ""),
    },
    "openrouter": {
        "deep_think_llm": os.getenv("PLANNER_MODEL_ID", "z-ai/glm-4.5-air:free"),
        "quick_think_llm": os.getenv("PLANNER_MODEL_ID", "z-ai/glm-4.5-air:free"),
        "backend_url": "https://openrouter.ai/api/v1",
    },
}

_defaults = _PROVIDER_DEFAULTS.get(_provider, _PROVIDER_DEFAULTS["openai"])

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "./results"),
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),
    # LLM settings — driven by env vars PRIMARY_PROVIDER, DEEP_THINK_LLM, QUICK_THINK_LLM
    "llm_provider": _provider,
    "deep_think_llm": os.getenv("DEEP_THINK_LLM", _defaults["deep_think_llm"]),
    "quick_think_llm": os.getenv("QUICK_THINK_LLM", _defaults["quick_think_llm"]),
    "backend_url": os.getenv("BACKEND_URL", _defaults["backend_url"]),
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
}
