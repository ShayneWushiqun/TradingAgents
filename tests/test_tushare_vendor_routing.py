from tradingagents.dataflows.interface import VENDOR_LIST, VENDOR_METHODS


def test_tushare_vendor_registered_for_core_analysis_methods():
    assert "tushare" in VENDOR_LIST
    assert "tushare" in VENDOR_METHODS["get_stock_data"]
    assert "tushare" in VENDOR_METHODS["get_indicators"]
    assert "tushare" in VENDOR_METHODS["get_fundamentals"]
    assert "tushare" in VENDOR_METHODS["get_balance_sheet"]
    assert "tushare" in VENDOR_METHODS["get_cashflow"]
    assert "tushare" in VENDOR_METHODS["get_income_statement"]
