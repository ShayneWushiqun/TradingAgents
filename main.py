from dotenv import load_dotenv
load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["max_debate_rounds"] = 1

config["data_vendors"] = {
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "yfinance",
    "news_data": "yfinance",
}

print(f"Provider: {config['llm_provider']}")
print(f"Deep model: {config['deep_think_llm']}")
print(f"Quick model: {config['quick_think_llm']}")
print(f"Backend URL: {config['backend_url']}")

ta = TradingAgentsGraph(debug=True, config=config)

_, decision = ta.propagate("NVDA", "2024-05-10")
print(decision)
