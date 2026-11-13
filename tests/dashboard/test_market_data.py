"""Chart rows stay on the supplied Yahoo frame. Failures are not filled with prices."""

import pandas as pd
import pytest

from backend.services.market_data import MarketDataError, load_chart
from tradingagents.dataflows.errors import NoMarketDataError


def _frame():
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]),
            "Open": [10, 11, 12],
            "High": [11, 12, 13],
            "Low": [9, 10, 11],
            "Close": [10.5, 11.5, 12.5],
            "Volume": [100, 110, 120],
        }
    )


def test_chart_uses_the_loader_rows_and_names_the_source(monkeypatch):
    monkeypatch.setattr(
        "backend.services.market_data._indicators",
        lambda frame: ({}, None),
    )
    chart = load_chart("AAPL", "2020-01-06", loader=lambda ticker, as_of: _frame())
    assert chart["source"] == "yfinance"
    assert chart["ok"] is True
    assert [row["close"] for row in chart["candles"]] == [10.5, 11.5, 12.5]
    assert chart["reference_price"] == 12.5
    assert chart["bar_date"] == "2020-01-06"
    assert chart["previous_close"] == 11.5
    assert chart["currency"] is None


def test_rows_after_the_analysis_date_are_excluded():
    chart = load_chart(
        "AAPL",
        "2020-01-03",
        loader=lambda ticker, as_of: _frame(),
    )
    assert chart["bar_date"] == "2020-01-03"
    assert chart["reference_price"] == 11.5
    assert len(chart["candles"]) == 2


def test_vendor_failure_raises_instead_of_substituting_prices():
    def fail(ticker, as_of):
        raise NoMarketDataError(ticker, ticker, "empty")

    with pytest.raises(MarketDataError) as raised:
        load_chart("MISSING", "2020-01-02", loader=fail)
    assert raised.value.code == "no_market_data"
    assert "MISSING" in raised.value.message
