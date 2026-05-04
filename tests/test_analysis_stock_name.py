"""Unified stock_name enrichment via ``resolve_stock_name`` and ``GET /api/stocks/{ts_code}/name``."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tradingagents.web.analysis_cache import AnalysisCache
from tradingagents.web.analysis_service import AnalysisService
from tradingagents.web.app import create_app
from tradingagents.web.schemas import AnalysisRequest
from tradingagents.web.tasks import TaskRegistry


def test_create_analysis_enriches_missing_stock_name(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def fake_resolve(code: str) -> str:
        return {"600186.SH": "莲花控股", "002081.SZ": "金螳螂"}.get(code, "")

    registry = TaskRegistry()
    service = AnalysisService(
        registry,
        runner=lambda request, config, emit: ({"final_trade_decision": "Rating: Hold"}, "Hold"),
        run_inline=True,
        cache=AnalysisCache(cache_dir=tmp_path / "cache"),
        runtime_dir=tmp_path,
        store=None,
    )

    with patch("tradingagents.web.analysis_service.resolve_stock_name", side_effect=fake_resolve):
        task = service.create_task(
            AnalysisRequest(ts_code="600186.SH", trade_date="2026-04-30", force_refresh=True)
        )

    assert task.request.stock_name == "莲花控股"


def test_create_analysis_enriches_when_stock_name_equals_ts_code(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def fake_resolve(code: str) -> str:
        return "莲花控股" if code == "600186.SH" else ""

    registry = TaskRegistry()
    service = AnalysisService(
        registry,
        runner=lambda request, config, emit: ({"final_trade_decision": "Rating: Hold"}, "Hold"),
        run_inline=True,
        cache=AnalysisCache(cache_dir=tmp_path / "cache"),
        runtime_dir=tmp_path,
        store=None,
    )

    with patch("tradingagents.web.analysis_service.resolve_stock_name", side_effect=fake_resolve):
        task = service.create_task(
            AnalysisRequest(
                ts_code="600186.SH",
                stock_name="600186.SH",
                trade_date="2026-04-30",
                force_refresh=True,
            )
        )

    assert task.request.stock_name == "莲花控股"


def test_history_enriches_missing_stock_name_from_resolver(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def fake_resolve(code: str) -> str:
        return "莲花控股" if code == "600186.SH" else ""

    registry = TaskRegistry()
    service = AnalysisService(
        registry,
        runner=lambda request, config, emit: ({"final_trade_decision": "Rating: Hold"}, "Hold"),
        run_inline=True,
        cache=AnalysisCache(cache_dir=tmp_path / "cache"),
        runtime_dir=tmp_path,
        store=None,
    )

    req = AnalysisRequest(ts_code="600186.SH", trade_date="2026-04-30", stock_name="", force_refresh=True)
    task = registry.create(req)
    registry.complete(task.task_id, {"final_trade_decision": "Rating: Hold"}, "Hold")

    with patch("tradingagents.web.analysis_service.resolve_stock_name", side_effect=fake_resolve):
        rows = service.history(limit=10)

    assert rows and rows[0]["request"]["stock_name"] == "莲花控股"


def test_history_enriches_missing_stock_name_from_report_text_when_resolver_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    registry = TaskRegistry()
    service = AnalysisService(
        registry,
        runner=lambda request, config, emit: ({"final_trade_decision": "Rating: Hold"}, "Hold"),
        run_inline=True,
        cache=AnalysisCache(cache_dir=tmp_path / "cache"),
        runtime_dir=tmp_path,
        store=None,
    )

    req = AnalysisRequest(ts_code="002081.SZ", trade_date="2026-04-30", stock_name="", force_refresh=True)
    task = registry.create(req)
    registry.complete(
        task.task_id,
        {
            "final_trade_decision": "Rating: Hold",
            "market_report": "# 002081.SZ（金螳螂）深度技术分析报告",
        },
        "Hold",
    )

    with patch("tradingagents.web.analysis_service.resolve_stock_name", return_value=""):
        rows = service.history(limit=10)

    assert rows and rows[0]["request"]["stock_name"] == "金螳螂"


def test_stock_name_endpoint_resolves_name(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    with patch("tradingagents.web.app.resolve_stock_name", return_value="莲花控股"):
        client = TestClient(create_app())
        response = client.get("/api/stocks/600186.SH/name")

    assert response.status_code == 200
    assert response.json() == {"ts_code": "600186.SH", "stock_name": "莲花控股"}


def test_stock_name_endpoint_invalid_code_returns_empty_name(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app())
    response = client.get("/api/stocks/not-a-code/name")
    assert response.status_code == 200
    body = response.json()
    assert body["stock_name"] == ""
    assert "ts_code" in body


def test_task_payload_enriches_stock_name_for_api(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")

    def fake_resolve(code: str) -> str:
        return "金螳螂" if code == "002081.SZ" else ""

    registry = TaskRegistry()
    service = AnalysisService(
        registry,
        runner=lambda request, config, emit: ({"final_trade_decision": "Rating: Hold"}, "Hold"),
        run_inline=True,
        cache=AnalysisCache(cache_dir=tmp_path / "cache"),
        runtime_dir=tmp_path,
        store=None,
    )

    task = registry.create(AnalysisRequest(ts_code="002081.SZ", trade_date="2026-04-30", force_refresh=True))
    registry.complete(task.task_id, {"final_trade_decision": "Rating: Hold"}, "Hold")

    with patch("tradingagents.web.analysis_service.resolve_stock_name", side_effect=fake_resolve):
        enriched = service.enrich_request_for_response(task.request)

    assert enriched.stock_name == "金螳螂"
