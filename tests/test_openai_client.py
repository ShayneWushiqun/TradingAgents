import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tradingagents.llm_clients.openai_client import NormalizedChatOpenAI


def _deepseek_llm():
    return NormalizedChatOpenAI(
        model="deepseek-reasoner",
        base_url="https://api.deepseek.com",
        api_key="test-key",
    )


@pytest.mark.unit
def test_deepseek_reasoning_content_is_preserved_from_response():
    llm = _deepseek_llm()
    response = {
        "id": "chatcmpl-test",
        "model": "deepseek-reasoner",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "Need to fetch price data first.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "get_stock_data",
                                "arguments": '{"symbol": "000066.SZ"}',
                            },
                        }
                    ],
                },
            }
        ],
    }

    result = llm._create_chat_result(response)

    message = result.generations[0].message
    assert message.additional_kwargs["reasoning_content"] == (
        "Need to fetch price data first."
    )


@pytest.mark.unit
def test_deepseek_reasoning_content_is_sent_back_with_tool_result():
    llm = _deepseek_llm()
    ai_message = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "Need to fetch price data first."},
        tool_calls=[
            {
                "id": "call_1",
                "name": "get_stock_data",
                "args": {"symbol": "000066.SZ"},
            }
        ],
    )

    payload = llm._get_request_payload(
        [
            HumanMessage(content="000066.SZ"),
            ai_message,
            ToolMessage(content="price data", tool_call_id="call_1"),
        ]
    )

    assistant_message = payload["messages"][1]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["reasoning_content"] == (
        "Need to fetch price data first."
    )
