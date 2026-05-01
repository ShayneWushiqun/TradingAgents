from fastapi.testclient import TestClient

from tradingagents.web.app import create_app


def test_health_reports_tushare_configuration(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "data_source": "tushare",
        "tushare_configured": True,
    }


def test_index_serves_workstation_html():
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "A股单股智能分析工作台" in response.text


def test_create_analysis_task_returns_task_id(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app())

    response = client.post(
        "/api/analysis",
        json={
            "ts_code": "600519.SH",
            "trade_date": "2026-04-30",
            "analysts": ["market", "fundamentals"],
            "research_depth": 1,
            "llm_provider": "deepseek",
            "quick_model": "deepseek-chat",
            "deep_model": "deepseek-chat",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"]
    assert body["status"] == "queued"


def test_chat_endpoint_returns_contextual_reply(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app())
    created = client.post(
        "/api/analysis",
        json={
            "ts_code": "600519.SH",
            "trade_date": "2026-04-30",
            "analysts": ["market", "fundamentals"],
            "research_depth": 1,
            "llm_provider": "deepseek",
            "quick_model": "deepseek-chat",
            "deep_model": "deepseek-chat",
        },
    ).json()

    response = client.post(
        "/api/chat",
        json={
            "task_id": created["task_id"],
            "message": "成交额下降怎么办？",
        },
    )

    assert response.status_code == 200
    assert "reply" in response.json()
    assert "600519.SH" in response.json()["reply"]
