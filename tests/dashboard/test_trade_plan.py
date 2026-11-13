"""Position sizing and hypothesis parsing. No model calls."""

from backend.services.trade_plan import (
    PositionInputs,
    assemble_trade_plan,
    calculate_position,
    extract_hypotheses,
    parse_labeled_price,
)

TRADER = """**Action**: Buy

**Reasoning**: The reports support a long.

**Entry Price**: 100

**Stop Loss**: 95

**Position Sizing**: 5% of portfolio

FINAL TRANSACTION PROPOSAL: **BUY**
"""

DECISION = """**Rating**: Buy

**Executive Summary**: Scale in near the planned entry.

**Investment Thesis**: The evidence is constructive.

**Price Target**: 110

**Time Horizon**: 3-6 months
"""


def test_labeled_price_rejects_placeholders_and_percentages():
    assert parse_labeled_price("**Entry Price**: not provided", "Entry Price") is None
    assert parse_labeled_price("**Stop Loss**: 15%", "Stop Loss") is None
    assert parse_labeled_price("**Entry Price**: 150-160", "Entry Price") is None
    assert parse_labeled_price("**Entry Price**: $1,234.50", "Entry Price") == 1234.5


def test_hypotheses_come_only_from_labeled_lines():
    hypotheses = extract_hypotheses(TRADER, DECISION)
    assert hypotheses["entry_price"] == 100
    assert hypotheses["stop_loss"] == 95
    assert hypotheses["price_target"] == 110
    assert hypotheses["action"] == "Buy"
    assert hypotheses["rating"] == "Buy"
    assert hypotheses["status"] == "available"


def test_position_size_uses_the_tightest_limit():
    sizing = calculate_position(
        PositionInputs(
            entry_price=100,
            stop_loss=95,
            price_target=110,
            action="Buy",
            available_capital=10000,
            available_cash=10000,
            max_risk_amount=200,
            max_position_percent=50,
            cost_bps=0,
        )
    )
    assert sizing["status"] == "available"
    assert sizing["shares"] == 40
    assert sizing["shares_by_risk"] == 40
    assert sizing["shares_by_allocation"] == 50
    assert sizing["shares_by_cash"] == 100
    assert sizing["planned_loss"] == 200
    assert sizing["capital_used"] == 4000
    assert sizing["remaining_cash"] == 6000
    assert sizing["risk_reward"] == 2
    assert sizing["binding_constraint"] == ["max_risk"]
    assert sizing["limit_entries"] == [{"price": 100, "shares": 40, "source": "research_hypothesis"}]
    assert sizing["entry_zone"]["status"] == "unavailable"
    assert sizing["exits"] == [{"price": 110, "shares": 40, "source": "research_hypothesis"}]


def test_cost_basis_reduces_cash_shares_and_increases_capital_used():
    sizing = calculate_position(
        PositionInputs(
            entry_price=100,
            stop_loss=95,
            price_target=110,
            action="Buy",
            available_capital=10000,
            available_cash=10000,
            max_risk_amount=200,
            max_position_percent=50,
            cost_bps=100,
        )
    )
    assert sizing["shares"] == 33
    assert sizing["capital_used"] == 3333
    assert sizing["remaining_cash"] == 6667
    assert sizing["shares_by_cash"] == 99


def test_missing_capital_does_not_invent_a_size():
    sizing = calculate_position(
        PositionInputs(entry_price=100, stop_loss=95, price_target=110, action="Buy")
    )
    assert sizing["status"] == "unavailable"
    assert sizing["shares"] is None
    assert "available capital" in sizing["reason"]
    assert sizing["limit_entries"][0]["shares"] is None


def test_user_prices_are_split_and_a_single_entry_is_not_a_zone():
    sizing = calculate_position(
        PositionInputs(
            entry_price=100,
            stop_loss=90,
            price_target=120,
            action="Buy",
            available_capital=10000,
            available_cash=10000,
            max_risk_amount=1000,
            max_position_percent=100,
            scale_in_prices=[100, 98],
            take_profit_prices=[110, 120],
        )
    )
    assert sizing["shares"] == 101
    assert [row["shares"] for row in sizing["limit_entries"]] == [51, 50]
    assert [row["price"] for row in sizing["limit_entries"]] == [100, 98]
    assert sizing["entry_zone"] == {
        "status": "available",
        "low": 98,
        "high": 100,
        "source": "user",
        "reason": None,
    }
    assert [row["shares"] for row in sizing["exits"]] == [51, 50]
    assert all(row["source"] == "user" for row in sizing["exits"])


def test_equal_entry_and_stop_has_no_risk():
    sizing = calculate_position(
        PositionInputs(
            entry_price=50,
            stop_loss=50,
            available_capital=1000,
            available_cash=1000,
            max_risk_amount=100,
            max_position_percent=10,
        )
    )
    assert sizing["status"] == "unavailable"
    assert "not positive" in sizing["reason"]


def test_conflicting_stop_withholds_risk_reward():
    sizing = calculate_position(
        PositionInputs(
            entry_price=100,
            stop_loss=110,
            price_target=120,
            action="Buy",
            available_capital=10000,
            available_cash=10000,
            max_risk_amount=500,
            max_position_percent=50,
        )
    )
    assert sizing["status"] == "unavailable"
    assert sizing["risk_reward"] is None
    assert sizing["invalidation"]["status"] == "available"


def test_assemble_marks_verified_and_generated_separately():
    plan = assemble_trade_plan(
        ticker="AAPL",
        analysis_date="2020-01-02",
        reports={"trader_investment_plan": TRADER, "final_trade_decision": DECISION},
        reference={
            "status": "available",
            "source": "yfinance",
            "price": 99.5,
            "bar_date": "2020-01-02",
            "error": None,
        },
        preferences={
            "available_capital": 10000,
            "available_cash": 10000,
            "max_risk_amount": 200,
            "max_position_percent": 50,
            "cost_bps": 0,
            "scale_in_prices": [],
            "take_profit_prices": [],
        },
    )
    assert plan["orders_sent"] is False
    assert plan["verified_market"]["price"] == 99.5
    assert plan["verified_market"]["source"] == "yfinance"
    assert plan["hypotheses"]["source"] == "generated_research"
    assert plan["hypotheses"]["entry_price"] == 100
    assert plan["sizing"]["shares"] == 40
    assert plan["limit_entries"][0]["source"] == "research_hypothesis"


def test_unavailable_reference_price_is_explicit():
    plan = assemble_trade_plan(
        ticker="AAPL",
        analysis_date="2020-01-02",
        reports={},
        reference={"status": "unavailable", "source": "yfinance", "price": None, "error": "No market data"},
        preferences={},
    )
    assert plan["verified_market"]["price"] is None
    assert plan["hypotheses"]["status"] == "unavailable"
    assert plan["sizing"]["shares"] is None
    assert plan["entry_zone"]["status"] == "unavailable"
    assert "No entry price" in plan["entry_zone"]["reason"]
