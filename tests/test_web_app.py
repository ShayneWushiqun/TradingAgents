from fastapi.testclient import TestClient

from tradingagents.web.app import create_app
from tradingagents.web.chat_service import ChatLLMUnavailable, DeepSeekChatLLM
from tradingagents.web.schemas import AnalysisRequest


def test_health_reports_tushare_configuration(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "data_source": "tushare",
        "tushare_configured": True,
        "auth_enabled": False,
        "analysis_store_configured": False,
        "analysis_store_available": False,
        "analysis_store_error": "",
        "hot_radar_store_configured": False,
        "hot_radar_store_available": False,
        "hot_radar_store_error": "",
        "database_required": False,
    }


def test_auth_password_protects_pages_and_apis():
    client = TestClient(create_app(auth_password="secret"))

    page = client.get("/", follow_redirects=False)
    api = client.get("/api/analysis/history")
    login_page = client.get("/login")

    assert page.status_code == 303
    assert page.headers["location"].startswith("/login")
    assert api.status_code == 401
    assert api.json()["detail"] == "not authenticated"
    assert login_page.status_code == 200
    assert "A-Share Insight" in login_page.text


def test_login_sets_eight_hour_cookie_and_allows_access():
    client = TestClient(create_app(auth_password="secret", auth_username="admin"))

    failed = client.post("/api/login", json={"username": "admin", "password": "bad"})
    success = client.post("/api/login", json={"username": "admin", "password": "secret"})
    page = client.get("/")

    assert failed.status_code == 401
    assert success.status_code == 200
    assert success.json()["ok"] is True
    assert "Max-Age=28800" in success.headers["set-cookie"]
    assert page.status_code == 200
    assert "A-Share Insight" in page.text


def test_logout_clears_auth_cookie():
    client = TestClient(create_app(auth_password="secret"))
    client.post("/api/login", json={"password": "secret"})

    response = client.post("/api/logout")
    blocked = client.get("/api/analysis/history")

    assert response.status_code == 200
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert blocked.status_code == 401


def test_create_app_can_require_database_url_for_runtime():
    try:
        create_app(database_url="", require_database=True)
    except RuntimeError as exc:
        assert "TRADINGAGENTS_DB_URL" in str(exc)
    else:  # pragma: no cover - defensive guard
        raise AssertionError("create_app should fail fast when the runtime DB URL is missing")


def test_health_reports_mysql_backed_stores_when_database_url_is_set(tmp_path):
    client = TestClient(
        create_app(
            database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
            runtime_dir=tmp_path,
            enable_hot_radar_scheduler=False,
        )
    )

    body = client.get("/api/health").json()

    assert body["analysis_store_configured"] is True
    assert body["analysis_store_available"] is True
    assert body["hot_radar_store_configured"] is True
    assert body["hot_radar_store_available"] is True
    assert body["database_required"] is False


def test_index_serves_workstation_html():
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "A-Share Insight" in response.text


def test_agent_chat_page_served_from_dedicated_route():
    client = TestClient(create_app())

    response = client.get("/agent-chat")

    assert response.status_code == 200
    assert "Agent Chat" in response.text
    assert "chat-question" in response.text


def test_reports_page_served_from_dedicated_route():
    client = TestClient(create_app())

    response = client.get("/reports")

    assert response.status_code == 200
    assert "历史报告" in response.text
    assert "/api/analysis/history" in response.text


def test_settings_page_served_from_dedicated_route():
    client = TestClient(create_app())

    response = client.get("/settings")

    assert response.status_code == 200
    assert "数据与模型" in response.text
    assert "/api/health" in response.text


def test_project_runtime_directory_is_gitignored():
    gitignore = open(".gitignore", encoding="utf-8").read()

    assert ".tradingagents-runtime/" in gitignore


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
            "quick_model": "deepseek-v4-pro",
            "deep_model": "deepseek-v4-pro",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"]
    assert body["status"] == "queued"


def test_create_analysis_accepts_suffixless_a_share_code(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def fake_runner(request, config, emit):
        return ({"final_trade_decision": f"Rating: Hold\n{request.ts_code}"}, "Hold")

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))

    created = client.post(
        "/api/analysis",
        json={
            "ts_code": "000066",
            "trade_date": "2026-04-30",
            "analysts": ["market"],
            "research_depth": 3,
        },
    ).json()
    response = client.get(f"/api/analysis/{created['task_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["request"]["ts_code"] == "000066.SZ"
    assert body["request"]["research_depth"] == 3


def test_create_analysis_enriches_missing_stock_name(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    monkeypatch.setattr(
        "tradingagents.web.analysis_service.resolve_stock_name",
        lambda ts_code: "莲花控股" if ts_code == "600186.SH" else "",
    )

    def fake_runner(request, config, emit):
        return ({"final_trade_decision": f"Rating: Hold\n{request.stock_name}"}, "Hold")

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))

    created = client.post(
        "/api/analysis",
        json={
            "ts_code": "600186.SH",
            "trade_date": "2026-04-30",
            "analysts": ["market"],
            "research_depth": 3,
        },
    ).json()
    response = client.get(f"/api/analysis/{created['task_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["request"]["stock_name"] == "莲花控股"
    assert body["final_decision"] == "Rating: Hold\n莲花控股"


def test_analysis_queue_endpoint_reports_lanes(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    client = TestClient(create_app(runtime_dir=tmp_path))
    service = client.app.state.analysis_service
    task = service.registry.create(AnalysisRequest(ts_code="600519.SH", trade_date="2026-04-30"))
    service.registry.start(task.task_id)

    response = client.get("/api/analysis/queue")

    assert response.status_code == 200
    body = response.json()
    assert body["lanes"]["pro"]["capacity"] == 1
    assert body["lanes"]["flash"]["capacity"] == 3
    rows = (
        body["lanes"]["pro"]["running"]
        + body["lanes"]["pro"]["queued"]
        + body["lanes"]["pro"]["finished"]
    )
    assert task.task_id in {row["task_id"] for row in rows}


def test_analysis_queue_endpoint_is_not_shadowed_by_task_route(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    client = TestClient(
        create_app(
            analysis_runner=lambda request, config, emit: ({"final_trade_decision": "Rating: Hold"}, "Hold"),
            runtime_dir=tmp_path,
        )
    )

    response = client.get("/api/analysis/queue")

    assert response.status_code == 200
    assert response.json()["lanes"]["pro"]["capacity"] == 1


def test_analysis_history_status_completed_excludes_running_queue_items(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    client = TestClient(create_app(runtime_dir=tmp_path))
    service = client.app.state.analysis_service
    running = service.registry.create(AnalysisRequest(ts_code="600001.SH", trade_date="2026-04-30"))
    service.registry.start(running.task_id)
    completed = service.registry.create(AnalysisRequest(ts_code="600002.SH", trade_date="2026-04-30"))
    service.registry.complete(completed.task_id, {"final_trade_decision": "Rating: Hold"}, "Hold")

    response = client.get("/api/analysis/history?status=completed")

    assert response.status_code == 200
    task_ids = {row["task_id"] for row in response.json()["items"]}
    assert completed.task_id in task_ids
    assert running.task_id not in task_ids


def test_queue_delete_does_not_delete_completed_history(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def fake_runner(request, config, emit):
        return ({"final_trade_decision": "Rating: Hold"}, "Hold")

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))
    created = client.post(
        "/api/analysis",
        json={"ts_code": "600519.SH", "trade_date": "2026-04-30"},
    ).json()

    response = client.delete(f"/api/analysis/queue/{created['task_id']}")
    history = client.get("/api/analysis/history").json()
    queue = client.get("/api/analysis/queue").json()

    assert response.status_code == 200
    assert response.json()["removed_from_queue"] is True
    assert any(row["task_id"] == created["task_id"] for row in history["items"])
    assert created["task_id"] not in {
        row["task_id"]
        for lane in queue["lanes"].values()
        for group in ("running", "queued", "finished")
        for row in lane[group]
    }


def test_web_analysis_uses_akshare_tavily_tushare_news_priority(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    captured_config = {}

    def fake_runner(request, config, emit):
        captured_config.update(config)
        return ({"final_trade_decision": "Rating: Hold"}, "Hold")

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))

    response = client.post(
        "/api/analysis",
        json={"ts_code": "600519.SH", "trade_date": "2026-04-30", "analysts": ["news"]},
    )

    assert response.status_code == 200
    assert captured_config["data_vendors"]["news_data"] == "akshare,tavily,tushare"


def test_web_analysis_defaults_to_deepseek_pro_for_standard_and_deep_models(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    captured_config = {}

    def fake_runner(request, config, emit):
        captured_config.update(config)
        return ({"final_trade_decision": "Rating: Hold"}, "Hold")

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))

    response = client.post(
        "/api/analysis",
        json={"ts_code": "600519.SH", "trade_date": "2026-04-30"},
    )

    assert response.status_code == 200
    assert captured_config["quick_think_llm"] == "deepseek-v4-pro"
    assert captured_config["deep_think_llm"] == "deepseek-v4-pro"


def test_web_analysis_runtime_files_stay_inside_project(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    captured_config = {}

    def fake_runner(request, config, emit):
        captured_config.update(config)
        return ({"final_trade_decision": "Rating: Hold"}, "Hold")

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))

    response = client.post(
        "/api/analysis",
        json={"ts_code": "600519.SH", "trade_date": "2026-04-30"},
    )

    assert response.status_code == 200
    assert str(captured_config["data_cache_dir"]).startswith(str(tmp_path))
    assert str(captured_config["results_dir"]).startswith(str(tmp_path))
    assert str(captured_config["memory_log_path"]).startswith(str(tmp_path))


def test_chat_endpoint_returns_contextual_reply(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def _chat_offline(self, **kwargs):
        raise ChatLLMUnavailable("test: deterministic reply path")

    monkeypatch.setattr(DeepSeekChatLLM, "answer", _chat_offline)

    client = TestClient(create_app())
    created = client.post(
        "/api/analysis",
        json={
            "ts_code": "600519.SH",
            "trade_date": "2026-04-30",
            "analysts": ["market", "fundamentals"],
            "research_depth": 1,
            "llm_provider": "deepseek",
            "quick_model": "deepseek-v4-pro",
            "deep_model": "deepseek-v4-pro",
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
    body = response.json()
    assert "reply" in body
    assert "sections" in body
    assert body["sections"]["conclusion"]
    assert isinstance(body["sections"]["evidence"], list)
    assert body["sections"]["llm_provider"] == "deepseek"
    assert body["sections"]["llm_model"] == "deepseek-v4-flash"
    assert body["sections"]["expert_mode"] is False
    assert body["sections"]["llm_used"] is False
    assert body["task_id"] == created["task_id"]
    assert body["ts_code"] == "600519.SH"
    assert "600519.SH" in body["reply"]


def test_chat_endpoint_uses_latest_task_when_task_id_empty(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app())
    client.post(
        "/api/analysis",
        json={
            "ts_code": "000001.SZ",
            "trade_date": "2026-04-30",
            "analysts": ["market"],
            "research_depth": 1,
        },
    )

    response = client.post(
        "/api/chat",
        json={"task_id": "", "message": "总结下报告结论？"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"]
    assert payload["ts_code"] == "000001.SZ"
    assert payload["sections"]["skill"] == "report_context"
    assert payload["sections"]["llm_provider"] == "deepseek"


def test_chat_endpoint_uses_deepseek_v4_pro_when_expert_mode_enabled(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app())
    created = client.post(
        "/api/analysis",
        json={
            "ts_code": "600519.SH",
            "trade_date": "2026-04-30",
            "analysts": ["market"],
            "research_depth": 1,
        },
    ).json()

    response = client.post(
        "/api/chat",
        json={
            "task_id": created["task_id"],
            "message": "用专家模式复盘",
            "expert_mode": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sections"]["llm_model"] == "deepseek-v4-pro"
    assert payload["sections"]["expert_mode"] is True


def test_chat_endpoint_accepts_conversation_history(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app())
    created = client.post(
        "/api/analysis",
        json={
            "ts_code": "600519.SH",
            "trade_date": "2026-04-30",
            "analysts": ["market"],
            "research_depth": 1,
        },
    ).json()

    response = client.post(
        "/api/chat",
        json={
            "task_id": created["task_id"],
            "message": "接着上一轮说",
            "conversation_history": [
                {"role": "user", "content": "上一轮问了估值"},
                {"role": "assistant", "content": "上一轮回答了PE。"},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sections"]["history_messages"] == 2
    assert payload["sections"]["context_compressed"] is False


def test_chat_stream_endpoint_emits_agent_events(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app())
    created = client.post(
        "/api/analysis",
        json={
            "ts_code": "600519.SH",
            "trade_date": "2026-04-30",
            "analysts": ["market"],
            "research_depth": 1,
        },
    ).json()

    response = client.post(
        "/api/chat/stream",
        json={
            "task_id": created["task_id"],
            "message": "当前上涨预期在哪？",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert "event: tool_started" in text
    assert "event: tool_completed" in text
    assert "event: llm_started" in text
    assert "event: answer_delta" in text
    assert "event: completed" in text
    assert "600519.SH" in text


def test_chat_stream_endpoint_accepts_smart_search(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    from tradingagents.web.chat_skills import SkillResult

    class FakeExternalDataSkill:
        name = "external_data_tools"

        def run(self, context):
            return SkillResult(
                skill=self.name,
                conclusion="智能搜索已读取外部数据。",
                evidence=["Tushare 与腾讯财经可用。"],
                data_sources=["tushare", "tencent_finance"],
            )

    monkeypatch.setattr(
        "tradingagents.web.chat_skills.router.ExternalDataSkill",
        FakeExternalDataSkill,
    )
    client = TestClient(create_app())
    created = client.post(
        "/api/analysis",
        json={
            "ts_code": "600519.SH",
            "trade_date": "2026-04-30",
            "analysts": ["market"],
            "research_depth": 1,
        },
    ).json()

    response = client.post(
        "/api/chat/stream",
        json={
            "task_id": created["task_id"],
            "message": "现在需要智能搜索什么消息？",
            "smart_search": True,
        },
    )

    assert response.status_code == 200
    text = response.text
    assert "external_data_tools" in text
    assert '"smart_search": true' in text


def test_analysis_endpoint_runs_task_and_exposes_status(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def fake_runner(request, config, emit):
        emit("report_section", {"section": "market_report", "content": "技术面转强"})
        return (
            {
                "market_report": "技术面转强",
                "fundamentals_report": "基本面稳健",
                "final_trade_decision": "Rating: Buy\n分批增持。",
            },
            "Buy",
        )

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))
    created = client.post(
        "/api/analysis",
        json={
            "ts_code": "600519.SH",
            "trade_date": "2026-04-30",
            "analysts": ["market", "fundamentals"],
            "research_depth": 1,
            "llm_provider": "deepseek",
            "quick_model": "deepseek-v4-pro",
            "deep_model": "deepseek-v4-pro",
        },
    ).json()

    response = client.get(f"/api/analysis/{created['task_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["decision"] == "Buy"
    assert body["report_sections"]["market_report"] == "技术面转强"


def test_analysis_endpoint_reuses_cached_completed_result(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    calls = {"count": 0}

    def fake_runner(request, config, emit):
        calls["count"] += 1
        emit("report_section", {"section": "market_report", "content": "缓存技术面"})
        return (
            {
                "market_report": "缓存技术面",
                "final_trade_decision": "Rating: Hold\n等待。",
            },
            "Hold",
        )

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))
    payload = {"ts_code": "600519.SH", "trade_date": "2026-04-30"}

    first = client.post("/api/analysis", json=payload).json()
    second = client.post("/api/analysis", json=payload).json()

    assert calls["count"] == 1
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["status"] == "completed"

    status = client.get(f"/api/analysis/{second['task_id']}").json()
    assert status["report_sections"]["market_report"] == "缓存技术面"
    assert status["final_decision"] == "Rating: Hold\n等待。"


def test_analysis_endpoint_force_refresh_bypasses_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    calls = {"count": 0}

    def fake_runner(request, config, emit):
        calls["count"] += 1
        return (
            {
                "market_report": f"第 {calls['count']} 次技术面",
                "final_trade_decision": f"Rating: Hold\n第 {calls['count']} 次。",
            },
            "Hold",
        )

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))
    payload = {"ts_code": "600519.SH", "trade_date": "2026-04-30"}

    client.post("/api/analysis", json=payload)
    refreshed = client.post(
        "/api/analysis",
        json={**payload, "force_refresh": True},
    ).json()

    assert calls["count"] == 2
    assert refreshed["cached"] is False

    status = client.get(f"/api/analysis/{refreshed['task_id']}").json()
    assert status["report_sections"]["market_report"] == "第 2 次技术面"


def test_restore_analysis_uses_cache_without_starting_new_run(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    calls = {"count": 0}

    def fake_runner(request, config, emit):
        calls["count"] += 1
        return (
            {
                "market_report": "恢复用技术面",
                "final_trade_decision": "Rating: Hold\n恢复缓存。",
            },
            "Hold",
        )

    first_client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))
    payload = {"ts_code": "600519.SH", "trade_date": "2026-04-30"}
    first_client.post("/api/analysis", json=payload)

    second_client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))
    restored = second_client.post("/api/analysis/restore", json=payload)

    assert restored.status_code == 200
    assert calls["count"] == 1
    body = restored.json()
    assert body["cached"] is True
    assert body["status"] == "completed"

    status = second_client.get(f"/api/analysis/{body['task_id']}").json()
    assert status["report_sections"]["market_report"] == "恢复用技术面"
    assert status["final_decision"] == "Rating: Hold\n恢复缓存。"


def test_restore_analysis_returns_404_when_cache_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def fake_runner(request, config, emit):
        raise AssertionError("restore endpoint must not start a new analysis")

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))

    response = client.post(
        "/api/analysis/restore",
        json={"ts_code": "600519.SH", "trade_date": "2026-04-30"},
    )

    assert response.status_code == 404


def test_latest_analysis_prefers_running_task(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def slow_runner(request, config, emit):
        emit("report_section", {"section": "market_report", "content": "运行中报告"})
        import time

        time.sleep(0.2)
        return ({"final_trade_decision": "Rating: Hold"}, "Hold")

    client = TestClient(create_app(analysis_runner=None, runtime_dir=tmp_path))
    client.app.state.analysis_service.runner = slow_runner

    created = client.post(
        "/api/analysis",
        json={"ts_code": "600519.SH", "trade_date": "2026-04-30"},
    ).json()
    latest = client.get("/api/analysis/latest")

    assert latest.status_code == 200
    assert latest.json()["task_id"] == created["task_id"]
    assert latest.json()["status"] in {"queued", "running"}


def test_latest_analysis_restores_latest_completed_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    calls = {"count": 0}

    def fake_runner(request, config, emit):
        calls["count"] += 1
        return (
            {
                "market_report": "最近缓存报告",
                "final_trade_decision": "Rating: Hold\n最近缓存。",
            },
            "Hold",
        )

    first_client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))
    first_client.post(
        "/api/analysis",
        json={"ts_code": "600519.SH", "trade_date": "2026-04-30"},
    )

    second_client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))
    latest = second_client.get("/api/analysis/latest")

    assert latest.status_code == 200
    assert calls["count"] == 1
    body = latest.json()
    assert body["cached"] is True
    assert body["status"] == "completed"


def test_analysis_history_uses_persistent_store(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    database_url = f"sqlite:///{tmp_path / 'analysis.db'}"

    def fake_runner(request, config, emit):
        return (
            {
                "market_report": "历史记录技术面",
                "final_trade_decision": "Rating: Hold\n历史记录。",
            },
            "Hold",
        )

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path, database_url=database_url))
    client.post(
        "/api/analysis",
        json={"ts_code": "600118.SH", "trade_date": "2026-04-30"},
    )

    response = client.get("/api/analysis/history")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["request"]["ts_code"] == "600118.SH"

    limited = client.get("/api/analysis/history", params={"limit": 120})
    assert limited.status_code == 200
    assert limited.json()["items"][0]["request"]["ts_code"] == "600118.SH"
    assert body["items"][0]["status"] == "completed"


def test_delete_analysis_soft_deletes_store_record_and_keeps_local_files(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    database_url = f"sqlite:///{tmp_path / 'analysis.db'}"

    def fake_runner(request, config, emit):
        return (
            {
                "market_report": "待删除技术面",
                "final_trade_decision": "Rating: Hold\n待删除。",
            },
            "Hold",
        )

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path, database_url=database_url))
    created = client.post(
        "/api/analysis",
        json={"ts_code": "600118.SH", "trade_date": "2026-04-30"},
    ).json()
    status = client.get(f"/api/analysis/{created['task_id']}").json()
    cache_key = status["request"]["ts_code"] + ":" + status["request"]["trade_date"]

    cache_files = list((tmp_path / "cache" / "web_analysis").glob("*.json"))
    report_file = (
        tmp_path
        / "reports"
        / "600118.SH"
        / "TradingAgentsStrategy_logs"
        / "full_states_log_2026-04-30.json"
    )
    report_file.parent.mkdir(parents=True)
    report_file.write_text('{"raw": true}', encoding="utf-8")

    response = client.delete(f"/api/analysis/{created['task_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is True
    assert body["task_id"] == created["task_id"]
    assert body["deleted_files"] == 0
    assert body["soft_deleted"] is True
    assert cache_key == "600118.SH:2026-04-30"
    assert report_file.exists()
    assert all(path.exists() for path in cache_files)
    assert client.get(f"/api/analysis/{created['task_id']}").status_code == 404
    assert client.get("/api/analysis/history").json()["items"] == []
    stored = client.app.state.analysis_store.get_task(created["task_id"], include_deleted=True)
    assert stored is not None
    assert stored["deleted_at"]


def test_latest_analysis_restores_failed_task_with_partial_reports_from_store(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    database_url = f"sqlite:///{tmp_path / 'analysis.db'}"

    def failing_runner(request, config, emit):
        emit("report_section", {"section": "market_report", "content": "失败前技术面"})
        emit("report_section", {"section": "fundamentals_report", "content": "失败前基本面"})
        raise RuntimeError("provider interrupted")

    first_client = TestClient(create_app(analysis_runner=failing_runner, runtime_dir=tmp_path, database_url=database_url))
    created = first_client.post(
        "/api/analysis",
        json={"ts_code": "603629.SH", "trade_date": "2026-04-30"},
    ).json()

    second_client = TestClient(create_app(analysis_runner=failing_runner, runtime_dir=tmp_path, database_url=database_url))
    latest = second_client.get("/api/analysis/latest")

    assert latest.status_code == 200
    body = latest.json()
    assert body["task_id"] == created["task_id"]
    assert body["status"] == "failed"
    assert body["report_sections"]["market_report"] == "失败前技术面"
    assert body["report_sections"]["fundamentals_report"] == "失败前基本面"


def test_analysis_status_restores_task_by_id_from_store(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    database_url = f"sqlite:///{tmp_path / 'analysis.db'}"

    def failing_runner(request, config, emit):
        emit("report_section", {"section": "market_report", "content": "按 ID 恢复技术面"})
        raise RuntimeError("provider interrupted")

    first_client = TestClient(create_app(analysis_runner=failing_runner, runtime_dir=tmp_path, database_url=database_url))
    created = first_client.post(
        "/api/analysis",
        json={"ts_code": "603629.SH", "trade_date": "2026-04-30"},
    ).json()

    second_client = TestClient(create_app(analysis_runner=failing_runner, runtime_dir=tmp_path, database_url=database_url))
    response = second_client.get(f"/api/analysis/{created['task_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == created["task_id"]
    assert body["status"] == "failed"
    assert body["report_sections"]["market_report"] == "按 ID 恢复技术面"


def test_history_reconciles_completed_report_marked_failed_by_raw_log_bug(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    database_url = f"sqlite:///{tmp_path / 'analysis.db'}"

    def raw_log_bug_runner(request, config, emit):
        emit("report_section", {"section": "market_report", "content": "技术面已完成"})
        emit("report_section", {"section": "final_trade_decision", "content": "Rating: Hold\n最终持有。"})
        raise TypeError("unsupported operand type(s) for /: 'PosixPath' and 'NoneType'")

    client = TestClient(create_app(analysis_runner=raw_log_bug_runner, runtime_dir=tmp_path, database_url=database_url))
    created = client.post(
        "/api/analysis",
        json={"ts_code": "000988.SZ", "trade_date": "2026-04-30"},
    ).json()

    history = client.get("/api/analysis/history").json()["items"][0]
    status = client.get(f"/api/analysis/{created['task_id']}").json()

    assert history["status"] == "completed"
    assert history["error"] == ""
    assert status["status"] == "completed"
    assert status["final_decision"] == "Rating: Hold\n最终持有。"


def test_analysis_events_stream_sse_progress(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def fake_runner(request, config, emit):
        emit("agent_started", {"agent": "Market Analyst"})
        emit("report_section", {"section": "market_report", "content": "技术面转强"})
        return ({"final_trade_decision": "Rating: Hold\n等待确认。"}, "Hold")

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))
    created = client.post(
        "/api/analysis",
        json={"ts_code": "600519.SH", "trade_date": "2026-04-30"},
    ).json()

    with client.stream("GET", f"/api/analysis/{created['task_id']}/events") as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: task_started" in body
    assert "event: task_progress" in body
    assert "event: agent_started" in body
    assert "event: report_section" in body
    assert "event: task_completed" in body


def test_streaming_graph_sets_ticker_before_writing_raw_report(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    class FakeMemoryLog:
        def get_past_context(self, ticker):
            return ""

        def store_decision(self, ticker, trade_date, final_trade_decision):
            return None

    class FakePropagator:
        def create_initial_state(self, ticker, trade_date, past_context=""):
            return {"ticker": ticker, "trade_date": trade_date}

        def get_graph_args(self):
            return {}

    class FakeCompiledGraph:
        def stream(self, init_state, **args):
            yield {
                "company_of_interest": init_state["ticker"],
                "trade_date": init_state["trade_date"],
                "market_report": "技术面完成",
                "sentiment_report": "情绪完成",
                "news_report": "新闻完成",
                "fundamentals_report": "基本面完成",
                "investment_debate_state": {"judge_decision": "投资计划"},
                "trader_investment_plan": "交易计划",
                "risk_debate_state": {"judge_decision": "Rating: Hold\n最终持有。"},
                "investment_plan": "投资计划",
                "final_trade_decision": "Rating: Hold\n最终持有。",
            }

    class FakeTradingGraph:
        def __init__(self, selected_analysts, debug, config):
            self.ticker = None
            self.propagator = FakePropagator()
            self.memory_log = FakeMemoryLog()
            self.graph = FakeCompiledGraph()
            self.curr_state = None

        def _log_state(self, trade_date, final_state):
            if self.ticker is None:
                raise TypeError("unsupported operand type(s) for /: 'PosixPath' and 'NoneType'")

        def process_signal(self, final_decision):
            return "Hold"

    monkeypatch.setattr(
        "tradingagents.web.analysis_service.TradingAgentsGraph",
        FakeTradingGraph,
    )
    client = TestClient(create_app(runtime_dir=tmp_path))

    created = client.post(
        "/api/analysis",
        json={"ts_code": "000988.SZ", "trade_date": "2026-04-30"},
    ).json()
    response = client.get(f"/api/analysis/{created['task_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["decision"] == "Hold"
    assert body["report_sections"]["final_trade_decision"] == "Rating: Hold\n最终持有。"


def test_analysis_endpoint_records_runner_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def failing_runner(request, config, emit):
        raise RuntimeError("LLM provider is not configured")

    client = TestClient(create_app(analysis_runner=failing_runner, runtime_dir=tmp_path))
    created = client.post(
        "/api/analysis",
        json={"ts_code": "600519.SH", "trade_date": "2026-04-30"},
    ).json()

    response = client.get(f"/api/analysis/{created['task_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert "LLM provider is not configured" in body["error"]


def test_export_markdown_returns_full_report(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def fake_runner(request, config, emit):
        emit("report_section", {"section": "market_report", "content": "### 市场\n完整技术面"})
        return (
            {
                "market_report": "### 市场\n完整技术面 /Users/evil/secret/path",
                "fundamentals_report": "基本面段落含 API_KEY 字样",
                "news_report": "新闻 TOKEN 独立词测试",
                "sentiment_report": "情绪面",
                "investment_plan": "研究辩论结论",
                "trader_investment_plan": "交易计划详情",
                "final_trade_decision": "Rating: Hold\n最终持有。",
            },
            "Hold",
        )

    client = TestClient(create_app(analysis_runner=fake_runner, runtime_dir=tmp_path))
    created = client.post(
        "/api/analysis",
        json={
            "ts_code": "600519.SH",
            "trade_date": "2026-04-30",
            "analysts": ["market", "fundamentals"],
            "research_depth": 2,
            "llm_provider": "deepseek",
            "quick_model": "deepseek-chat",
            "deep_model": "deepseek-chat",
        },
    ).json()

    response = client.get(f"/api/analysis/{created['task_id']}/export.md")

    assert response.status_code == 200
    assert "text/markdown" in response.headers.get("content-type", "")
    text = response.text
    assert "# TradingAgents A股完整分析报告" in text
    assert "600519.SH" in text
    assert "2026-04-30" in text
    assert "market" in text and "fundamentals" in text
    assert "research_depth" in text
    assert "llm_provider" in text
    assert "Rating: Hold" in text
    assert "完整技术面" in text
    assert "基本面段落" in text
    assert ".env" not in text
    assert "API_KEY" not in text
    assert "TOKEN" not in text
    assert "/Users/evil" not in text
    disposition = response.headers.get("content-disposition", "").lower()
    assert "tradingagents-600519.sh-2026-04-30-full-report.md" in disposition


def test_export_markdown_returns_404_for_unknown_task(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app(runtime_dir=tmp_path))

    response = client.get("/api/analysis/deadbeefdeadbeefdeadbeefdeadbeef/export.md")

    assert response.status_code == 404


def test_export_markdown_returns_409_while_running(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app(runtime_dir=tmp_path))

    class _Running:
        status = "running"

    monkeypatch.setattr(client.app.state.analysis_service, "get_task", lambda _tid: _Running())

    response = client.get("/api/analysis/any-task-id/export.md")

    assert response.status_code == 409
    assert "进行中" in response.json()["detail"]


def test_export_markdown_returns_409_for_failed_without_content(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def fail_runner(request, config, emit):
        raise RuntimeError("LLM provider is not configured")

    client = TestClient(create_app(analysis_runner=fail_runner, runtime_dir=tmp_path))
    created = client.post(
        "/api/analysis",
        json={"ts_code": "600519.SH", "trade_date": "2026-04-30"},
    ).json()

    response = client.get(f"/api/analysis/{created['task_id']}/export.md")

    assert response.status_code == 409


def test_workstation_html_includes_export_and_no_save_memory():
    from pathlib import Path

    html = Path("docs/design/a-share-workstation.html").read_text(encoding="utf-8")
    assert "导出报告" in html
    assert "/export.md" in html
    assert "保存记忆" not in html


def test_hot_radar_api_runs_batch_and_returns_dashboard(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def fake_runner(request, config, emit):
        return (
            {
                "market_report": f"{request.ts_code} 热榜初筛",
                "final_trade_decision": "Rating: Hold\n热榜轻量观察。",
            },
            "Hold",
        )

    def fake_snapshot(trade_date, top_n):
        return {
            "trade_date": trade_date,
            "top_n": top_n,
            "markets": {
                "热股": [
                    {
                        "trade_date": trade_date,
                        "market": "热股",
                        "ts_code": "000988.SZ",
                        "ts_name": "华工科技",
                        "rank": 1,
                        "hot": 96.8,
                        "pct_change": 7.42,
                        "current_price": 119.53,
                        "concept": "CPO;光模块",
                        "rank_reason": "10点新进",
                        "rank_time": "10:03:18",
                    }
                ],
                "ETF": [],
                "行业板块": [],
                "概念板块": [],
            },
        }

    client = TestClient(
        create_app(
            analysis_runner=fake_runner,
            runtime_dir=tmp_path,
            database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
            hot_snapshot_getter=fake_snapshot,
            trade_dates_getter=lambda end_date, limit: ["2026-04-30", "2026-04-29"],
            enable_hot_radar_scheduler=False,
        )
    )

    run_response = client.post(
        "/api/hot-radar/run",
        json={"trade_date": "2026-04-30", "batch_time": "daily", "top_n": 10},
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["run"]["status"] == "completed"
    assert run_payload["items"]["热股"][0]["ts_code"] == "000988.SZ"
    assert run_payload["analysis_tasks"][0]["status"] == "completed"

    dashboard = client.get("/api/hot-radar?trade_date=2026-04-30&batch_time=daily").json()
    assert dashboard["run"]["trade_date"] == "2026-04-30"
    assert dashboard["items"]["热股"][0]["ts_name"] == "华工科技"

    dashboard_default_batch = client.get("/api/hot-radar?trade_date=2026-04-30").json()
    assert dashboard_default_batch["run"]["batch_time"] == "daily"
    assert dashboard_default_batch["items"]["热股"][0]["ts_code"] == "000988.SZ"


def test_hot_radar_run_rejects_unknown_report_models(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(
        create_app(
            runtime_dir=tmp_path,
            database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
            enable_hot_radar_scheduler=False,
        )
    )
    response = client.post(
        "/api/hot-radar/run",
        json={
            "trade_date": "2026-04-30",
            "batch_time": "daily",
            "top_n": 10,
            "quick_model": "gpt-4o",
            "deep_model": "gpt-4o",
        },
    )
    assert response.status_code == 422


def test_hot_radar_fetch_snapshot_endpoint(monkeypatch, tmp_path):
    """fetch_if_missing=false stays DB-only; default GET pulls once into store; POST /fetch forces refresh."""

    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    td = "2026-06-07"
    snapshots = {"n": 0}

    def fake_snapshot(trade_date, top_n):
        snapshots["n"] += 1
        suffix = f"-v{snapshots['n']}"
        return {
            "trade_date": trade_date,
            "top_n": top_n,
            "markets": {
                "热股": [
                    {
                        "trade_date": trade_date,
                        "market": "热股",
                        "ts_code": "688000.SH",
                        "ts_name": f"测试热股{suffix}",
                        "rank": 1,
                        "hot": 99.0,
                        "pct_change": 8.1,
                        "rank_reason": "测试",
                        "rank_time": "09:30:00",
                    }
                ],
                "ETF": [
                    {
                        "trade_date": trade_date,
                        "market": "ETF",
                        "ts_code": "510300.SH",
                        "ts_name": "测试ETF",
                        "rank": 1,
                        "hot": 50.0,
                        "pct_change": 0.5,
                        "rank_reason": "ETF榜",
                        "rank_time": "09:30:00",
                    }
                ],
                "行业板块": [],
                "概念板块": [],
            },
        }

    cal_days = ["2026-06-07", "2026-06-05", "2026-04-30", "2026-04-29"]

    def trade_dates_getter(end_date, limit):
        end = end_date or "2099-12-31"
        return [d for d in cal_days if d <= end][:limit]

    client = TestClient(
        create_app(
            runtime_dir=tmp_path,
            database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
            hot_snapshot_getter=fake_snapshot,
            trade_dates_getter=trade_dates_getter,
            enable_hot_radar_scheduler=False,
        )
    )

    empty = client.get(
        "/api/hot-radar",
        params={"trade_date": td, "batch_time": "daily", "top_n": 10, "fetch_if_missing": "false"},
    ).json()
    assert empty["run"]["status"] == "missing"
    assert snapshots["n"] == 0

    first_fill = client.get(
        "/api/hot-radar",
        params={"trade_date": td, "batch_time": "daily", "top_n": 10},
    ).json()
    assert first_fill["run"]["status"] == "hot_only"
    assert first_fill["items"]["热股"][0]["ts_name"] == "测试热股-v1"
    assert snapshots["n"] == 1

    cached_after_get = client.get(
        "/api/hot-radar",
        params={"trade_date": td, "batch_time": "daily", "top_n": 10},
    ).json()
    assert cached_after_get["items"]["热股"][0]["ts_name"] == "测试热股-v1"
    assert snapshots["n"] == 1

    fetched = client.post(
        "/api/hot-radar/fetch",
        json={"trade_date": td, "batch_time": "daily", "top_n": 10, "force_refresh": True},
    ).json()
    assert fetched["run"]["status"] == "hot_only"
    assert fetched["items"]["热股"][0]["ts_name"] == "测试热股-v2"
    assert fetched["items"]["ETF"][0]["ts_name"] == "测试ETF"
    assert snapshots["n"] == 2

    stored = client.get(
        "/api/hot-radar",
        params={"trade_date": td, "batch_time": "daily", "top_n": 10, "fetch_if_missing": "false"},
    ).json()
    assert stored["run"]["status"] == "hot_only"
    assert stored["items"]["热股"][0]["ts_name"] == "测试热股-v2"


def test_hot_radar_trade_dates_api_uses_trade_calendar(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(
        create_app(
            runtime_dir=tmp_path,
            database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
            trade_dates_getter=lambda end_date, limit: ["2026-04-30", "2026-04-29"],
            enable_hot_radar_scheduler=False,
        )
    )

    response = client.get("/api/hot-radar/trade-dates")

    assert response.status_code == 200
    assert response.json()["items"] == ["2026-04-30", "2026-04-29"]
