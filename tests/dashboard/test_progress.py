"""Phase changes follow report fields. They do not invent a percentage."""

from backend.services.progress import ProgressState, extract_reports


def test_analysts_complete_only_when_their_report_arrives():
    state = ProgressState(["market", "news"])
    state.begin_analysts()
    assert state.phase == "analysts"
    assert state.agent_status["Market Analyst"] == "in_progress"
    assert state.agent_status["News Analyst"] == "in_progress"
    assert "Sentiment Analyst" not in state.agent_status

    notes = state.apply_chunk({"market_report": "Trend is up."})
    assert state.agent_status["Market Analyst"] == "completed"
    assert state.agent_status["News Analyst"] == "in_progress"
    assert state.phase == "analysts"
    assert notes == ["Market Analyst completed"]

    state.apply_chunk({"news_report": "Headline risk is low."})
    assert state.phase == "research_debate"
    assert state.agent_status["Bull Researcher"] == "in_progress"


def test_debate_trader_risk_and_portfolio_follow_the_cli_fields():
    state = ProgressState(["market"])
    state.begin_analysts()
    state.apply_chunk({"market_report": "Ready."})
    state.apply_chunk({"investment_debate_state": {"bull_history": "Bull case.", "bear_history": ""}})
    assert state.reports["bull_history"] == "Bull case."
    assert state.phase == "research_debate"

    state.apply_chunk({"investment_plan": "Research manager plan."})
    assert state.agent_status["Research Manager"] == "completed"
    assert state.agent_status["Trader"] == "in_progress"
    assert state.phase == "trader"

    state.apply_chunk({"trader_investment_plan": "**Action**: Buy"})
    assert state.phase == "risk_debate"
    assert state.agent_status["Aggressive Analyst"] == "in_progress"

    state.apply_chunk(
        {
            "risk_debate_state": {
                "aggressive_history": "Press the position.",
                "conservative_history": "Keep it small.",
                "neutral_history": "Split the difference.",
            }
        }
    )
    assert state.phase == "risk_debate"
    state.apply_chunk({"final_trade_decision": "**Rating**: Buy"})
    assert state.agent_status["Portfolio Manager"] == "completed"
    assert state.agent_status["Neutral Analyst"] == "completed"
    assert state.phase == "reports_ready"


def test_empty_chunk_does_not_complete_anyone():
    state = ProgressState(["fundamentals"])
    state.begin_analysts()
    notes = state.apply_chunk(None)
    assert notes == []
    assert state.agent_status["Fundamentals Analyst"] == "in_progress"


def test_extract_reports_keeps_only_text_sections():
    reports = extract_reports(
        {
            "market_report": " Market ",
            "sentiment_report": "",
            "investment_debate_state": {"bull_history": "Bull", "bear_history": "  "},
            "final_trade_decision": "Decision",
        }
    )
    assert reports["market_report"] == "Market"
    assert "sentiment_report" not in reports
    assert reports["bull_history"] == "Bull"
    assert reports["final_trade_decision"] == "Decision"
