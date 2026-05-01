from pathlib import Path


def test_a_share_workstation_prototype_exists_with_key_sections():
    html_path = Path("docs/design/a-share-workstation.html")

    assert html_path.exists()

    html = html_path.read_text(encoding="utf-8")
    required_labels = [
        "A股单股智能分析工作台",
        "Tushare Pro 已连接",
        "积分 6,240",
        "常规投研接口",
        "需要提示",
        "600519.SH",
        "多智能体分析流程",
        "组合经理决策",
        "开始分析",
        "Analyze",
        "分析股票",
        "Agent 对话分析",
        "历史聊天",
        "已注入上下文",
        "开启 Agent 对话",
        "分析运行中",
        "报告已生成",
        "chat-question",
        "/api/health",
        "/api/tushare/stocks/",
        "/api/analysis",
    ]

    for label in required_labels:
        assert label in html
