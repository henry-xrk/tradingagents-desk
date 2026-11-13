"""Phase status copied from the CLI stream, without a made-up percentage.

Analysts run together. An agent is completed only after its report text is
present in a streamed state chunk. Debate phases follow the same fields the
CLI watches in ``cli/run.py``.
"""

from __future__ import annotations

ANALYST_ORDER = ("market", "social", "news", "fundamentals")

ANALYST_NAMES = {
    "market": "Market Analyst",
    "social": "Sentiment Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}

ANALYST_REPORTS = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}

RESEARCH_TEAM = ("Bull Researcher", "Bear Researcher", "Research Manager")
RISK_TEAM = ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst")

REPORT_KEYS = (
    "market_report",
    "sentiment_report",
    "news_report",
    "fundamentals_report",
    "bull_history",
    "bear_history",
    "investment_plan",
    "trader_investment_plan",
    "aggressive_history",
    "conservative_history",
    "neutral_history",
    "final_trade_decision",
)


def extract_reports(state: dict | None) -> dict[str, str]:
    """Pull the saved report sections out of a graph state."""
    if not state:
        return {}
    debate = state.get("investment_debate_state") or {}
    risk = state.get("risk_debate_state") or {}
    raw = {
        "market_report": state.get("market_report"),
        "sentiment_report": state.get("sentiment_report"),
        "news_report": state.get("news_report"),
        "fundamentals_report": state.get("fundamentals_report"),
        "bull_history": debate.get("bull_history"),
        "bear_history": debate.get("bear_history"),
        "investment_plan": state.get("investment_plan"),
        "trader_investment_plan": state.get("trader_investment_plan"),
        "aggressive_history": risk.get("aggressive_history"),
        "conservative_history": risk.get("conservative_history"),
        "neutral_history": risk.get("neutral_history"),
        "final_trade_decision": state.get("final_trade_decision"),
    }
    return {key: value.strip() for key, value in raw.items() if isinstance(value, str) and value.strip()}


class ProgressState:
    """Mutable agent status for one run."""

    def __init__(self, selected: list[str]):
        self.selected = [key for key in ANALYST_ORDER if key in selected]
        self.agent_status: dict[str, str] = {}
        for key in self.selected:
            self.agent_status[ANALYST_NAMES[key]] = "pending"
        for name in (*RESEARCH_TEAM, "Trader", *RISK_TEAM, "Portfolio Manager"):
            self.agent_status[name] = "pending"
        self.reports: dict[str, str] = {}
        self.phase = "queued"

    def begin_analysts(self) -> None:
        self.phase = "analysts"
        for key in self.selected:
            name = ANALYST_NAMES[key]
            if self.agent_status.get(name) == "pending":
                self.agent_status[name] = "in_progress"

    def apply_chunk(self, chunk: dict | None) -> list[str]:
        """Apply one streamed chunk. Return notes for status changes only."""
        before = dict(self.agent_status)
        if chunk:
            self._apply_analysts(chunk)
            self._apply_research(chunk)
            self._apply_trader(chunk)
            self._apply_risk(chunk)
        self.phase = self.derived_phase()
        completed = [
            name
            for name, status in self.agent_status.items()
            if status == "completed" and before.get(name) != "completed"
        ]
        if completed:
            return [", ".join(completed) + " completed"]
        started = [
            name
            for name, status in self.agent_status.items()
            if status == "in_progress" and before.get(name) == "pending"
        ]
        if "Bull Researcher" in started:
            return ["Research debate started"]
        if "Aggressive Analyst" in started and before.get("Trader") != "completed":
            return ["Risk debate started"]
        if started:
            return [", ".join(started) + " started"]
        return []

    def derived_phase(self) -> str:
        if any(self.agent_status.get(ANALYST_NAMES[key]) != "completed" for key in self.selected):
            return "analysts"
        if any(self.agent_status.get(name) != "completed" for name in RESEARCH_TEAM):
            return "research_debate"
        if self.agent_status.get("Trader") != "completed":
            return "trader"
        if any(self.agent_status.get(name) != "completed" for name in RISK_TEAM):
            return "risk_debate"
        if self.agent_status.get("Portfolio Manager") != "completed":
            return "portfolio_manager"
        return "reports_ready"

    def _mark(self, name: str, status: str) -> None:
        if self.agent_status.get(name) == "completed" and status != "completed":
            return
        self.agent_status[name] = status

    def _apply_analysts(self, chunk: dict) -> None:
        all_filed = True
        for key in self.selected:
            report_key = ANALYST_REPORTS[key]
            name = ANALYST_NAMES[key]
            text = chunk.get(report_key)
            if isinstance(text, str) and text.strip():
                self.reports[report_key] = text.strip()
            if self.reports.get(report_key):
                self._mark(name, "completed")
            else:
                self._mark(name, "in_progress")
                all_filed = False
        if all_filed and self.selected and self.agent_status.get("Bull Researcher") == "pending":
            self._mark("Bull Researcher", "in_progress")

    def _apply_research(self, chunk: dict) -> None:
        debate = chunk.get("investment_debate_state")
        if isinstance(debate, dict):
            bull = (debate.get("bull_history") or "").strip()
            bear = (debate.get("bear_history") or "").strip()
            if bull:
                self.reports["bull_history"] = bull
            if bear:
                self.reports["bear_history"] = bear
            if bull or bear:
                for name in RESEARCH_TEAM:
                    self._mark(name, "in_progress")
        plan = chunk.get("investment_plan")
        if isinstance(plan, str) and plan.strip():
            self.reports["investment_plan"] = plan.strip()
            for name in RESEARCH_TEAM:
                self._mark(name, "completed")
            self._mark("Trader", "in_progress")

    def _apply_trader(self, chunk: dict) -> None:
        plan = chunk.get("trader_investment_plan")
        if isinstance(plan, str) and plan.strip():
            self.reports["trader_investment_plan"] = plan.strip()
            self._mark("Trader", "completed")
            self._mark("Aggressive Analyst", "in_progress")

    def _apply_risk(self, chunk: dict) -> None:
        risk = chunk.get("risk_debate_state")
        if isinstance(risk, dict):
            for key, name in (
                ("aggressive_history", "Aggressive Analyst"),
                ("conservative_history", "Conservative Analyst"),
                ("neutral_history", "Neutral Analyst"),
            ):
                text = (risk.get(key) or "").strip()
                if text:
                    self.reports[key] = text
                    self._mark(name, "in_progress")
        decision = chunk.get("final_trade_decision")
        if isinstance(decision, str) and decision.strip():
            self.reports["final_trade_decision"] = decision.strip()
            for name in (*RISK_TEAM, "Portfolio Manager"):
                self._mark(name, "completed")
