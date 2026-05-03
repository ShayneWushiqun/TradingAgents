from pathlib import Path


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
        "restoreCachedAnalysis",
        "loadLatestAnalysis",
        "loadAnalysisStatus",
        "hydrateAnalysisStatus",
        "导出报告",
        "export-report-btn",
        "exportFullReportMarkdown",
        "/export.md",
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


def test_workstation_layout_keeps_decision_panel_visible_on_wide_screens():
    html = Path("docs/design/a-share-workstation.html").read_text(encoding="utf-8")

    assert "max-width: none;" in html
    assert "overflow-x: auto;" in html
    assert "grid-template-columns: clamp(260px, 22vw, 340px) minmax(0, 1fr) clamp(320px, 24vw, 420px);" in html
    assert ".workspace > aside:last-child" in html
    assert "position: sticky;" in html
    assert "align-self: start;" in html
    assert "overflow-y: auto;" not in html
    assert "max-height: calc(100vh - 120px);" not in html


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
        "快速模式",
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
        "/api/analysis/restore",
        "DELETE",
        "删除记录",
        "载入报告",
        "任务状态",
        "报告列表",
        "report-list",
        "refresh-reports",
    ]

    for label in required_labels:
        assert label in html


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
    ]

    for label in required_labels:
        assert label in html


def test_workstation_restores_backend_latest_before_local_browser_state():
    html = Path("docs/design/a-share-workstation.html").read_text(encoding="utf-8")
    restore_start = html.index("async function restoreWorkspaceState()")
    restore_end = html.index("restoreWorkspaceState();", restore_start)
    restore_body = html[restore_start:restore_end]

    assert "let latestStatus = null;" in restore_body
    assert restore_body.index("await loadLatestAnalysis()") < restore_body.index("readWorkspaceState()")
    assert "已恢复最新分析" in restore_body


def test_decision_signal_parser_prioritizes_structured_underweight_rating():
    html = Path("docs/design/a-share-workstation.html").read_text(encoding="utf-8")
    parser_start = html.index("function extractDecisionSignal")
    parser_end = html.index("function extractDecisionReasons", parser_start)
    parser_body = html[parser_start:parser_end]

    assert "structuredMatch" in parser_body
    assert "underweight" in parser_body
    assert "return \"减仓\";" in parser_body
    assert "source.includes(\"buy\")" not in parser_body


def test_hot_radar_calendar_sync_and_row_level_analysis_buttons():
    html = Path("docs/design/hot-radar.html").read_text(encoding="utf-8")

    assert 'class="hot-toolbar"' in html
    assert 'class="sync-latest-btn"' in html
    assert "基准日" in html
    assert "calendarTodayLocal" in html
    assert "force_refresh" in html
    assert "/api/hot-radar/trade-dates" not in html
    assert "enqueueAnalyzeFromHotRadar" in html
    assert "data-analyze-ts" in html
    assert "/api/analysis" in html
    assert "/api/analysis/history?limit=" in html
    assert "portfolioManagerBrief" in html
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
