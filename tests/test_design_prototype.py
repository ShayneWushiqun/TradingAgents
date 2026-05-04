from pathlib import Path
import re
import subprocess


def test_a_share_workstation_prototype_exists_with_key_sections():
    html_path = Path("docs/design/a-share-workstation.html")

    assert html_path.exists()

    html = html_path.read_text(encoding="utf-8")
    required_labels = [
        "A-Share Insight",
        "Tushare Pro 已连接",
        "积分 6,240",
        "常规投研接口",
        "需要提示",
        "多智能体分析流程",
        "组合经理决策",
        "开始分析",
        "强制重新分析",
        "Analyze",
        "分析股票",
        "开启 Agent 对话",
        "/agent-chat",
        "/reports",
        "/settings",
        "分析运行中",
        "报告已生成",
        "stock-code",
        "stock-options",
        "trade-date",
        "parseStockInput",
        "inferAshareTsCode",
        "getCurrentSelection",
        "getSelectedAnalysts",
        "getSelectedResearchDepth",
        "updateDecisionPanel",
        "extractDecisionSignal",
        "snapshot.is_fallback",
        "requested_trade_date",
        "decision-signal",
        "resetReportSummary",
        "appendReportStage",
        "syncDecisionPanelFromFinalReport",
        "reportSections.final_trade_decision",
        "showReportSection",
        "renderMarkdownDocument",
        "renderMarkdownTable",
        "isMarkdownTableSeparator",
        "<table>",
        "<thead>",
        "<tbody>",
        "report-section-tab",
        "report-viewer",
        "report-document",
        "final_trade_decision",
        "等待选择股票",
        "请选择 A 股代码和分析交易日",
        "data-analyst=\"market\"",
        "data-depth=\"3\"",
        "000066.SZ",
        "/api/health",
        "/api/tushare/stocks/",
        "/api/analysis",
        "EventSource",
        "/events",
        "task_failed",
        "report_section",
        "force_refresh",
        "cache_hit",
        "WORKSTATION_STATE_KEY",
        "saveWorkspaceState",
        "restoreWorkspaceState",
        "tsPrefill",
        'params.get("stock_name")',
        "namePrefill",
        "cacheStockDisplayName",
        "replaceState",
        "restoreCachedAnalysis",
        "loadLatestAnalysis",
        "loadAnalysisStatus",
        "hydrateAnalysisStatus",
        "导出报告",
        "export-report-btn",
        "exportFullReportMarkdown",
        "/export.md",
        "formatBoardShort",
        "601991.SH",
        "大唐发电",
        "fetchStockNameFromApi",
        "/api/stocks/",
    ]

    for label in required_labels:
        assert label in html

    assert "保存记忆" not in html

    assert "价格走势与量能" not in html
    assert "price-chart" not in html
    assert "A股单股智能分析工作台" not in html
    assert "Agent 对话分析" not in html
    assert "chat-question" not in html
    assert '<input class="field-box active" id="stock-code" list="stock-options" value=' not in html


def test_hot_radar_analysis_link_passes_stock_name_to_workstation():
    hot_html = Path("docs/design/hot-radar.html").read_text(encoding="utf-8")
    workstation_html = Path("docs/design/a-share-workstation.html").read_text(encoding="utf-8")

    assert "stock_name" in hot_html
    assert "data-analyze-name" in hot_html
    assert "activeAnalysisModalRow.stockName" in hot_html
    assert "stock_name: activeAnalysisModalRow.stockName" in hot_html
    assert "params.get(\"stock_name\")" in workstation_html
    assert "cacheStockDisplayName(prefillCode, namePrefill)" in workstation_html


def test_workstation_layout_keeps_decision_panel_visible_on_wide_screens():
    html = Path("docs/design/a-share-workstation.html").read_text(encoding="utf-8")

    assert "max-width: none;" in html
    assert "overflow-x: auto;" in html
    assert "grid-template-columns: clamp(260px, 22vw, 340px) minmax(0, 1fr) clamp(320px, 24vw, 420px);" in html
    assert ".workspace > aside:last-child" in html
    assert "position: sticky;" in html
    assert "align-self: start;" in html
    decision_aside = re.search(r"\.workspace > aside:last-child \{([\s\S]+?)\n    \}", html)
    assert decision_aside
    assert "overflow-y: auto;" not in decision_aside.group(1)
    assert "max-height: calc(100vh - 120px);" not in decision_aside.group(1)


def test_workstation_inline_script_is_valid_javascript(tmp_path):
    html = Path("docs/design/a-share-workstation.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    assert scripts

    script_path = tmp_path / "a-share-workstation.js"
    script_path.write_text("\n".join(scripts), encoding="utf-8")
    result = subprocess.run(
        ["node", "--check", str(script_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_workstation_uses_pro_model_for_standard_and_deep_analysis():
    html = Path("docs/design/a-share-workstation.html").read_text(encoding="utf-8")

    assert 'data-depth="1"' not in html
    assert 'data-depth="3"' in html
    assert 'data-depth="5"' in html
    assert "报告分析模型" in html
    assert "report-model-selector" in html
    assert 'data-report-model="deepseek-v4-pro"' in html
    assert 'data-report-model="deepseek-v4-flash"' in html
    assert "restoreReportModelUI" in html
    assert "reportModelSegments" in html
    assert "REPORT_MODEL_STORAGE_KEY" in html
    assert "TRADINGAGENTS_REPORT_MODEL" in html
    assert "getSelectedReportModel" in html


def test_agent_chat_page_exists_with_task_context_and_chat_controls():
    html_path = Path("docs/design/agent-chat.html")

    assert html_path.exists()

    html = html_path.read_text(encoding="utf-8")
    required_labels = [
        "Agent Chat",
        "TradingAgents 报告上下文",
        "A-Share Insight",
        "Workspace",
        "rail-item active",
        "当前分析任务",
        "历史消息",
        "chat-history-list",
        "CHAT_HISTORY_STORAGE_KEY",
        "loadConversationHistory",
        "saveConversationHistory",
        "renderChatHistoryList",
        "restoreConversationMessages",
        "conversation_history",
        "context_compressed",
        "Shift+Enter 换行",
        'placeholder="继续追问当前股票的风险、预期或交易计划...（Enter 发送，Shift+Enter 换行）"',
        "chat-question",
        "send-chat",
        "composer-toolbar",
        "mode-actions",
        "quick-mode-toggle",
        "标准模式",
        "smart-search-toggle",
        "smartSearch",
        "智能搜索",
        "smart_search",
        "expert-mode-toggle",
        "expertMode",
        "专家模式",
        "expert_mode",
        "send-chat-loading",
        "context-stock",
        "chatgpt-layout",
        "chat-shell",
        "task-id-line",
        "overflow-wrap: anywhere;",
        "max-width: 880px;",
        "font-size: 14px;",
        "ensureChatContext",
        "submitAgentChat",
        "appendStructuredAssistantMessage",
        "buildStructuredAssistantHtml",
        "appendAgentTrace",
        "appendAgentTraceStep",
        "appendAssistantStreamingMessage",
        "appendAssistantDelta",
        "finalizeStreamingAssistantMessage",
        "readAgentStream",
        "data-agent-trace",
        "tool_started",
        "tool_completed",
        "llm_started",
        "external_data_tools",
        "腾讯财经",
        "answer_delta",
        "completed",
        "正在选择工具",
        "data-reply-block",
        "appendAssistantErrorBubble",
        "setSendLoading",
        "task_id",
        "/api/analysis/latest",
        "/api/chat/stream",
        "/api/chat",
        "/api/analysis/",
    ]

    for label in required_labels:
        assert label in html
    assert "估值压力" not in html
    assert "交易计划复盘" not in html
    assert "可用数据能力" not in html
    assert "Tushare A股数据" not in html
    assert "AKShare 新闻/公告" not in html
    assert "Tavily Search" not in html
    assert "专家模式 · deepseek" not in html
    assert ".thread.active" not in html
    assert 'value="继续追问当前股票的风险、预期或交易计划..."' not in html


def test_reports_page_exists_with_history_controls():
    html_path = Path("docs/design/reports.html")

    assert html_path.exists()

    html = html_path.read_text(encoding="utf-8")
    required_labels = [
        "历史报告",
        "A-Share Insight",
        "/api/analysis/history",
        "DELETE",
        "删除记录",
        "载入报告",
        "任务状态",
        "报告列表",
        "report-list",
        "refresh-reports",
        "/api/analysis/history?status=completed",
        "只展示已完成报告",
        "暂无已完成历史报告",
        'item.status === "completed"',
        "openReportTask",
        "?task_id=",
        "formatReportCardTitle",
        "resolveStockDisplayName",
        "fetchStockDisplayName",
        "hydrateReportNames",
        "/api/stocks/",
        "detail-name",
        "item.request?.stock_name",
        "REPORTS_HISTORY_CACHE_KEY",
        "readCachedReportsSnapshot",
        "writeCachedReportsSnapshot",
        "slimReportForStorage",
        "DB 为准",
    ]

    for label in required_labels:
        assert label in html

    forbidden_labels = [
        "RECENT_ANALYSIS_TASK_STORAGE_KEYS",
        "TRADINGAGENTS_RECENT_ANALYSIS_TASKS",
        "TRADINGAGENTS_HOT_RADAR_QUEUE_TASKS",
        "loadLocalCompletedReports",
        "readLocalAnalysisTaskSeeds",
        "/api/analysis/restore",
    ]
    for label in forbidden_labels:
        assert label not in html


def test_analyze_payload_and_reports_use_task_stock_name():
    workstation_html = Path("docs/design/a-share-workstation.html").read_text(encoding="utf-8")
    reports_html = Path("docs/design/reports.html").read_text(encoding="utf-8")

    assert "stock_name" in workstation_html
    assert "getCurrentStockDisplayName" in workstation_html
    assert "stock_name: getCurrentStockDisplayName(selection.tsCode)" in workstation_html
    assert "item.request?.stock_name" in reports_html


def test_reports_page_falls_back_to_completed_report_text_for_stock_name():
    reports_html = Path("docs/design/reports.html").read_text(encoding="utf-8")

    assert "extractStockNameFromText" in reports_html
    assert "extractStockNameFromReport" in reports_html
    assert "report_sections" in reports_html
    assert "final_decision" in reports_html
    assert "name = extractStockNameFromReport(next, ts)" in reports_html


def test_reports_page_uses_local_snapshot_only_as_fast_first_paint():
    reports_html = Path("docs/design/reports.html").read_text(encoding="utf-8")

    assert "readCachedReportsSnapshot()" in reports_html
    assert "renderReports(cachedItems, " in reports_html
    assert "/api/analysis/history?status=completed" in reports_html
    assert "writeCachedReportsSnapshot(hydrated)" in reports_html
    assert "clearCachedReportsSnapshot()" in reports_html
    assert "section_count" in reports_html
    assert "report_sections" in reports_html
    assert "本地快照" in reports_html
    assert "正在刷新 DB" in reports_html


def test_reports_page_offers_one_click_clear_all_completed():
    """Reports「一键清空」 button + DELETE call to ``/api/analysis/history?status=completed``."""

    reports_html = Path("docs/design/reports.html").read_text(encoding="utf-8")
    assert 'id="clear-reports"' in reports_html
    assert "一键清空" in reports_html
    assert "clearAllReports" in reports_html
    assert "/api/analysis/history?status=completed" in reports_html
    assert 'method: "DELETE"' in reports_html


def test_hot_radar_does_not_use_local_storage_for_task_state():
    html = Path("docs/design/hot-radar.html").read_text(encoding="utf-8")

    assert "/api/analysis/queue" in html
    assert "/api/analysis/history?limit=150" in html
    assert "/api/analysis/history?status=completed" in html
    for label in [
        "HOT_RADAR_QUEUE_STORAGE_KEY",
        "RECENT_ANALYSIS_TASK_STORAGE_KEY",
        "readTrackedQueueSeeds",
        "writeTrackedQueueSeeds",
        "rememberHotRadarQueueTask",
        "rememberRecentAnalysisTask",
        "loadTrackedQueueTasks",
        "forgetHotRadarQueueTask",
    ]:
        assert label not in html


def test_hot_radar_uses_snapshot_cache_without_treating_it_as_task_truth():
    html = Path("docs/design/hot-radar.html").read_text(encoding="utf-8")

    assert "HOT_RADAR_DASHBOARD_CACHE_PREFIX" in html
    assert "HOT_RADAR_COMPLETED_HISTORY_CACHE_KEY" in html
    assert "readHotRadarDashboardSnapshot" in html
    assert "writeHotRadarDashboardSnapshot" in html
    assert "readCompletedHistorySnapshot" in html
    assert "writeCompletedHistorySnapshot" in html
    assert "showCachedDashboardFirstPaint" in html
    assert "loadCompletedHistorySnapshot" in html
    assert "本地快照" in html
    assert "正在刷新后端数据" in html
    assert "/api/hot-radar?trade_date=" in html
    assert "/api/analysis/history?status=completed&limit=100" in html
    assert "completedHistoryItems = incoming" in html


def test_hot_radar_uses_inline_detail_popover_instead_of_native_help_cursor():
    html = Path("docs/design/hot-radar.html").read_text(encoding="utf-8")

    assert "detail-popover" in html
    assert "detailAttr(" in html
    assert "showDetailPopover" in html
    assert "data-detail" in html
    assert "cursor: help" not in html
    assert "titleAttr(" not in html
    assert " title=" not in html


def test_settings_page_exists_with_data_and_model_status():
    html_path = Path("docs/design/settings.html")

    assert html_path.exists()

    html = html_path.read_text(encoding="utf-8")
    required_labels = [
        "数据与模型",
        "A-Share Insight",
        "/api/health",
        "Tushare Pro",
        "MySQL 任务索引",
        "新闻源优先级",
        "akshare,tavily,tushare",
        "DeepSeek",
        "health-status",
        "deepseek-v4-flash",
    ]

    for label in required_labels:
        assert label in html

    """Report-model picker has moved into per-row analysis modals; settings page must not host it any more."""
    forbidden_in_settings = [
        "report-model-segmented",
        "report-model-card",
        "restoreReportModelUI",
        "TRADINGAGENTS_REPORT_MODEL",
        "id=\"report-model-pro\"",
        "id=\"report-model-flash\"",
    ]
    for label in forbidden_in_settings:
        assert label not in html


def test_workstation_restores_backend_latest_before_local_browser_state():
    html = Path("docs/design/a-share-workstation.html").read_text(encoding="utf-8")
    restore_start = html.index("async function restoreWorkspaceState()")
    restore_end = html.index("restoreWorkspaceState();", restore_start)
    restore_body = html[restore_start:restore_end]

    assert "let latestStatus = null;" in restore_body
    assert restore_body.index("await loadLatestAnalysis()") < restore_body.index("readWorkspaceState()")
    assert "已恢复最新分析" in restore_body
    assert "params.get(\"ts_code\")" in restore_body
    assert 'params.get("stock_name")' in restore_body
    assert restore_body.index("tsPrefill") < restore_body.index("await loadLatestAnalysis()")
    assert "已从热榜带入股票与交易日" in restore_body
    assert "待分析" in restore_body


def test_decision_signal_parser_prioritizes_structured_underweight_rating():
    html = Path("docs/design/a-share-workstation.html").read_text(encoding="utf-8")
    parser_start = html.index("function extractDecisionSignal")
    parser_end = html.index("function parseMarkdownTableRow", parser_start)
    parser_body = html[parser_start:parser_end]

    assert "structuredMatch" in parser_body
    assert "underweight" in parser_body
    assert "return \"减仓\";" in parser_body
    assert "source.includes(\"buy\")" not in parser_body


def test_workstation_risk_panel_uses_list_and_filters_markdown_tables():
    html = Path("docs/design/a-share-workstation.html").read_text(encoding="utf-8")

    assert "报告中未提取到明确风险提示，请查看完整交易报告。" in html
    assert "risk-bullets" in html
    assert "function isPanelStructuralJunk" in html
    risk_start = html.index("function extractRiskSentences")
    risk_end = html.index("function updateDecisionPanel", risk_start)
    risk_body = html[risk_start:risk_end]
    assert "isPanelStructuralJunk" in risk_body
    assert "tableRowToRiskShortLine" in risk_body

    update_start = html.index("function updateDecisionPanel")
    update_end = html.index("function syncDecisionPanelFromFinalReport", update_start)
    update_body = html[update_start:update_end]
    assert "decisionRisk.textContent" not in update_body
    assert 'createElement("ul")' in update_body

    panel_start = html.index(".risk-box {")
    panel_end = html.index(".tabs {", panel_start)
    risk_css = html[panel_start:panel_end]
    assert "max-height: 220px" not in risk_css
    assert ".risk-box .risk-bullets" in risk_css


def test_workstation_decision_panel_not_cleared_by_analyst_or_depth_chips():
    html = Path("docs/design/a-share-workstation.html").read_text(encoding="utf-8")

    analyst_start = html.index("至少保留一个分析师团队。")
    analyst_end = html.index("depthSegments.forEach", analyst_start)
    analyst_block = html[analyst_start:analyst_end]
    assert 'updateDecisionPanel("", "")' not in analyst_block
    assert "refreshDecisionPanelFromStoredFinal" in analyst_block
    assert "PARAM_CHANGE_PM_HINT" in analyst_block

    depth_dom = "depthSegments.forEach((segment) => {"
    depth_start = html.index(depth_dom, html.index(depth_dom) + 1)
    depth_end = html.index("reportTabs.forEach", depth_start)
    depth_block = html[depth_start:depth_end]
    assert 'updateDecisionPanel("", "")' not in depth_block
    assert "refreshDecisionPanelFromStoredFinal" in depth_block

    show_start = html.index("function showReportSection")
    show_end = html.index("function resetReportSummary", show_start)
    show_body = html[show_start:show_end]
    assert "syncDecisionPanelFromFinalReport();" in show_body

    run_start = html.index("async function runAnalysis")
    run_end = html.index("runButton.addEventListener", run_start)
    run_body = html[run_start:run_end]
    assert 'updateDecisionPanel("", "");' in run_body


def test_workstation_risk_extractor_logic_rejects_table_separator_lines():
    """Mirror key JS rules so Markdown table separator lines are never treated as risk text."""

    import re

    def parse_cells(line):
        return [c.strip() for c in line.strip().strip("|").split("|")]

    def is_markdown_table_separator(line):
        cells = parse_cells(line)
        return len(cells) > 1 and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)

    assert is_markdown_table_separator("| --- | --- |")
    assert is_markdown_table_separator("|:---|:---:|")
    assert not is_markdown_table_separator("| 风险 | 说明 |")


def test_hot_radar_calendar_sync_and_row_level_analysis_buttons():
    html = Path("docs/design/hot-radar.html").read_text(encoding="utf-8")

    assert "TRADINGAGENTS_REPORT_MODEL" in html
    assert "getSelectedReportModel" in html
    assert 'class="hot-toolbar"' in html
    assert 'class="sync-latest-btn"' in html
    assert "基准日" in html
    assert 'id="current-trade-date"' in html
    assert "buildCalendarDateOptions" in html
    assert "setTradeDateOptions(buildCalendarDateOptions(30))" in html
    assert "/api/hot-radar/trade-dates" not in html
    assert "force_refresh" in html
    assert "analysis-modal" in html
    assert "openAnalysisModal" in html
    assert "submitAnalysisModal" in html
    assert "queue-overview" in html
    assert "queue-panel" in html
    assert html.count('id="queue-panel"') == 1
    assert "loadAnalysisQueueFromHistory" in html
    assert "mergeQueuePayloads" in html
    assert "queueStatusLabel" in html
    assert "hotRadarNameForCode" in html
    assert "latestQueueApiAvailable" in html
    assert "loadAnalysisQueue" in html
    assert "renderAnalysisQueue(await loadAnalysisQueue())" in html
    assert "/api/analysis/queue" in html
    assert 'event.target.closest("[data-queue-action]")' in html
    assert "组合经理：排队中" in html
    assert "组合经理：停止中" in html
    assert "data-analyze-ts" in html
    assert "data-analyze-name" in html
    assert 'data-analyze-name="${escapeHtml(item.ts_name || "")}"' in html
    assert 'getAttribute("data-analyze-name")' in html
    assert 'origin: "hot_radar"' in html
    assert 'fetch("/api/analysis",' in html
    assert "/api/analysis/history?status=completed" in html
    assert "completedReportByStock" in html
    assert "hydrateCompletedReports" in html
    assert "pickCompletedForRow" in html
    assert "pickQueueTaskForRow" in html
    assert "mergeCompletedTaskLocal" in html
    assert "refreshHotRadarRowState" in html
    assert "buildActiveQueueIndex" in html
    assert "activeQueueByCodeDate" in html
    assert "!== \"completed\"" in html
    assert "组合经理：已完成" in html
    assert "portfolioManagerBrief" in html
    assert 'data-analyze-force="1"' in html
    assert "force_refresh: Boolean(activeAnalysisModalRow.forceRefresh)" in html
    assert "fetch_if_missing=false" in html
    assert "isoIsToday" in html
    assert "calendarTodayLocal()" in html
    assert "手动触发批量分析" not in html
    assert "runHotRadarBatch" not in html
    assert "dedupeHotItems" in html
    assert "/api/hot-radar/run" not in html
    assert "/api/hot-radar/fetch" in html
    assert "batch_time: \"daily\"" in html
    assert "history-date" not in html
    assert "历史参考" not in html
    assert "历史缺报告不会自动补跑" not in html
    assert "schedule-card" not in html
    assert "10:00" not in html
    assert "12:00" not in html
    assert "17:00" not in html
