"""Deterministic position sizing. The model does not do this arithmetic.

Entry, stop, and target prices are inputs. This module never invents a price.
Missing inputs stay unavailable, and share counts are integers.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

_NULLISH = {"", "none", "n/a", "na", "null", "nil", "-", "tbd", "unknown", "not provided"}
_LABEL = re.compile(r"^\*\*(?P<label>[^*]+)\*\*:\s*(?P<value>.*)$", re.MULTILINE)

DISCLAIMER = (
    "This is a research plan built from model output and a verified market snapshot. "
    "It is not a verified profitable signal, and no brokerage order is sent."
)

LIMITATIONS = [
    "Research output is not a verified profitable signal.",
    "No brokerage order is sent.",
    "Entry, stop, and target prices are model hypotheses unless a field says it is verified market data.",
    "The reference price is the latest Yahoo Finance close on or before the analysis date. It can be delayed or split-adjusted.",
    "Share quantities ignore lot size, taxes, and partial fills. The only trading cost is the basis-point assumption shown here.",
]


def _label_value(text: str | None, label: str) -> str | None:
    if not text:
        return None
    for match in _LABEL.finditer(text):
        if match.group("label").strip() != label:
            continue
        value = match.group("value").strip()
        if value.lower() in _NULLISH:
            return None
        return value
    return None


def parse_labeled_price(text: str | None, label: str) -> float | None:
    """Read one rendered price label. Percentages and ranges are rejected."""
    raw = _label_value(text, label)
    if raw is None or raw.endswith("%"):
        return None
    cleaned = raw.replace(",", "").lstrip("$€£¥").strip()
    if not cleaned or any(char.isspace() for char in cleaned) or "-" in cleaned[1:]:
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


_ACTION_WORDS = {"buy": "Buy", "sell": "Sell", "hold": "Hold", "reduce": "Reduce"}
_RATING_WORDS = {
    "buy": "Buy",
    "overweight": "Overweight",
    "hold": "Hold",
    "underweight": "Underweight",
    "sell": "Sell",
}


def _exact_choice(value: str | None, choices: dict[str, str]) -> str | None:
    if not value:
        return None
    return choices.get(value.strip().lower())


def _price_field(text: str | None, label: str) -> tuple[float | None, str]:
    """Return a price and whether the label was missing, stated absent, unreadable, or available."""
    if not text:
        return None, "missing"
    raw = None
    found = False
    for match in _LABEL.finditer(text):
        if match.group("label").strip() != label:
            continue
        found = True
        raw = match.group("value").strip()
        break
    if not found:
        return None, "missing"
    if raw is None or raw.lower() in _NULLISH:
        return None, "stated_absent"
    number = parse_labeled_price(f"**{label}**: {raw}", label)
    if number is None:
        return None, "unreadable"
    return number, "available"


def extract_hypotheses(
    trader_text: str | None,
    decision_text: str | None,
    investment_text: str | None = None,
) -> dict:
    """Prices stay on their labeled lines. The final action comes only from the decision."""
    decision = interpret_decision(trader_text, decision_text, investment_text)
    entry = decision["entry_price"]
    stop = decision["stop_loss"]
    target = decision["price_target"]
    missing = [
        name
        for name, value in (
            ("entry_price", entry),
            ("stop_loss", stop),
            ("price_target", target),
        )
        if value is None
    ]
    if missing and entry is None and stop is None and target is None:
        status = "unavailable"
    elif missing:
        status = "partial"
    else:
        status = "available"
    return {
        "status": status,
        "source": "generated_research",
        **decision,
        "missing": missing,
    }


def interpret_decision(
    trader_text: str | None,
    decision_text: str | None,
    investment_text: str | None = None,
) -> dict:
    """Read labeled ratings and actions. Prose is not searched for a trade."""
    trader_action = _exact_choice(_label_value(trader_text, "Action"), _ACTION_WORDS)
    rating = _exact_choice(_label_value(decision_text, "Rating"), _RATING_WORDS) or _exact_choice(
        _label_value(investment_text, "Recommendation"),
        _RATING_WORDS,
    )
    action = _exact_choice(_label_value(decision_text, "Action"), _ACTION_WORDS)
    conditions = _label_value(decision_text, "Executive Summary")
    thesis = _label_value(decision_text, "Investment Thesis") or _label_value(investment_text, "Rationale")
    horizon = _label_value(decision_text, "Time Horizon")
    entry, entry_state = _price_field(trader_text, "Entry Price")
    stop, stop_state = _price_field(trader_text, "Stop Loss")
    target, target_state = _price_field(decision_text, "Price Target")
    price_fields = {
        "entry_price": entry_state,
        "stop_loss": stop_state,
        "price_target": target_state,
    }
    if rating or action:
        final_status = "parsed"
        result_status = "readable"
        result_reason = None
    else:
        final_status = "needs_review"
        result_status = "needs_review"
        result_reason = "The final decision has no Rating, Recommendation, or Action label."
    action_note = None
    if action is None and (rating or trader_action):
        action_note = "The final decision has no Action label. The trader proposal is not the final action."
    stated = [
        name
        for name, state in price_fields.items()
        if state == "stated_absent"
    ]
    if rating in {"Underweight", "Overweight"} and action is None:
        plan_status = "not_applicable"
        plan_reason = (
            f"{rating} is a research rating, not a sell order. "
            "The current holding is unknown, so no reduce quantity was calculated."
        )
        if stated:
            plan_reason += " " + _stated_price_reason(stated)
        next_step = "Check the actual holding before sizing a reduction. Do not treat the rating as an order."
    elif entry is None or stop is None:
        plan_status = "missing_parameters"
        plan_reason = _stated_price_reason(stated) if stated else (
            "No entry price or stop loss parsed as one positive number, so no share count was calculated."
        )
        next_step = "Use the manual calculator for prices you type. Missing research prices stay missing."
    elif final_status != "parsed":
        plan_status = "parse_failed"
        plan_reason = result_reason
        next_step = "Read the saved decision text. No share count was calculated from it."
    else:
        plan_status = "ready"
        plan_reason = None
        next_step = None
    return {
        "action": action,
        "action_note": action_note,
        "trader_action": trader_action,
        "rating": rating,
        "final_status": final_status,
        "result_status": result_status,
        "result_reason": result_reason,
        "conditional": False,
        "conditions": conditions,
        "thesis": thesis,
        "applies_to": None,
        "horizon": horizon,
        "entry_price": entry,
        "stop_loss": stop,
        "price_target": target,
        "price_fields": price_fields,
        "plan_status": plan_status,
        "plan_reason": plan_reason,
        "next_step": next_step,
    }


def _stated_price_reason(stated: list[str]) -> str:
    labels = {
        "entry_price": "entry price",
        "stop_loss": "stop loss",
        "price_target": "price target",
    }
    names = [labels[name] for name in stated]
    if not names:
        return "Required prices were not reported."
    if len(names) == 1:
        joined = names[0]
    elif len(names) == 2:
        joined = f"{names[0]} and {names[1]}"
    else:
        joined = ", ".join(names[:-1]) + f", and {names[-1]}"
    verb = "is" if len(names) == 1 else "are"
    return f"The report states that the {joined} {verb} not provided, so no number was invented."


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _ratio(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _whole_shares(value: Decimal) -> int:
    if value <= 0:
        return 0
    return int(value.to_integral_value(rounding=ROUND_DOWN))


def _split(total: int | None, prices: list[float], source: str) -> list[dict]:
    if not prices:
        return []
    if total is None:
        return [{"price": price, "shares": None, "source": source} for price in prices]
    if total <= 0:
        return [{"price": price, "shares": 0, "source": source} for price in prices]
    base, extra = divmod(total, len(prices))
    rows = []
    for index, price in enumerate(prices):
        shares = base + (1 if index < extra else 0)
        rows.append({"price": price, "shares": shares, "source": source})
    return rows


@dataclass
class PositionInputs:
    entry_price: float | None = None
    stop_loss: float | None = None
    price_target: float | None = None
    action: str | None = None
    available_capital: float | None = None
    available_cash: float | None = None
    max_risk_amount: float | None = None
    max_risk_percent: float | None = None
    max_position_percent: float | None = None
    cost_bps: float = 0
    scale_in_prices: list[float] = field(default_factory=list)
    take_profit_prices: list[float] = field(default_factory=list)
    level_source: str | None = None


def calculate_position(inputs: PositionInputs) -> dict:
    """Size a position from explicit inputs. Missing inputs stay unavailable."""
    assumptions = [
        "Share count, planned loss, and capital use are calculated in Python.",
        f"Trading cost assumption: {inputs.cost_bps:g} basis points of entry notional. "
        "Zero means no commission or slippage is included.",
        "Planned loss is not a guaranteed maximum loss. A gap through the stop and exit costs are not included.",
    ]
    entry = inputs.entry_price
    stop = inputs.stop_loss
    target = inputs.price_target
    missing = _missing_inputs(inputs)
    invalidation = _invalidation(stop)
    price_source = inputs.level_source or ("user" if inputs.scale_in_prices else "research_hypothesis")
    exit_source = inputs.level_source or ("user" if inputs.take_profit_prices else "research_hypothesis")
    levels = _levels(entry, inputs.scale_in_prices, None, price_source)
    exits = _exits(target, inputs.take_profit_prices, None, assumptions, exit_source)
    zone = _entry_zone(inputs.scale_in_prices, entry)

    if missing:
        return _unavailable_sizing(
            "Sizing needs " + ", ".join(missing) + ".",
            assumptions,
            invalidation,
            levels,
            exits,
            zone,
            inputs,
        )
    if entry is None or stop is None or entry <= 0 or stop <= 0:
        return _unavailable_sizing(
            "Entry and stop prices must be positive.",
            assumptions,
            invalidation,
            levels,
            exits,
            zone,
            inputs,
        )
    if any(
        value is not None and value < 0
        for value in (
            inputs.available_capital,
            inputs.available_cash,
            inputs.max_risk_amount,
            inputs.cost_bps,
        )
    ):
        return _unavailable_sizing(
            "Capital, cash, risk, and cost must be zero or greater.",
            assumptions,
            invalidation,
            levels,
            exits,
            zone,
            inputs,
        )

    entry_d = _decimal(entry)
    stop_d = _decimal(stop)
    risk_per_share = abs(entry_d - stop_d)
    if risk_per_share <= 0:
        return _unavailable_sizing(
            "The stop and entry are the same price, so risk per share is not positive.",
            assumptions,
            invalidation,
            levels,
            exits,
            zone,
            inputs,
        )

    # This calculator sizes new cash-funded long positions only. A sell rating
    # cannot determine either a closing quantity or a margin-funded short.
    prices = inputs.scale_in_prices or [entry]
    if (inputs.action or "").strip().lower() not in {"buy", "overweight"} or any(price <= stop for price in prices) or stop >= entry:
        return _unavailable_sizing(
            "New-position sizing requires Buy/Overweight and a stop below every entry. "
            "Hold, sell, and short plans require separate position and margin information.",
            assumptions, invalidation, levels, exits, zone, inputs,
        )
    direction = "long"

    assert inputs.available_capital is not None
    assert inputs.available_cash is not None
    assert inputs.max_position_percent is not None
    amount_budget = _decimal(inputs.max_risk_amount) if inputs.max_risk_amount is not None else None
    percent_budget = None
    if inputs.max_risk_percent is not None:
        percent_budget = _decimal(inputs.available_capital) * _decimal(inputs.max_risk_percent) / Decimal(100)
    if amount_budget is not None and percent_budget is not None:
        risk_budget = min(amount_budget, percent_budget)
        tighter = "dollar amount" if amount_budget <= percent_budget else "risk percent"
        assumptions.append(
            "Both a risk amount and a risk percent were supplied. "
            f"The tighter budget is the {tighter}."
        )
    elif amount_budget is not None:
        risk_budget = amount_budget
        assumptions.append("Maximum risk uses the dollar amount.")
    else:
        assert percent_budget is not None
        risk_budget = percent_budget
        assumptions.append("Maximum risk dollars were derived from available capital and the risk percent.")

    cost_rate = _decimal(inputs.cost_bps) / Decimal(10000)
    prices_d = [_decimal(price) for price in prices]
    cash_costs = [price * (1 + cost_rate) for price in prices_d]
    loss_costs = [price - stop_d + price * cost_rate for price in prices_d]
    allocation_dollars = _decimal(inputs.available_capital) * _decimal(inputs.max_position_percent) / Decimal(100)
    shares_by_risk = _capacity(risk_budget, loss_costs)
    shares_by_allocation = _capacity(allocation_dollars, cash_costs)
    shares_by_cash = _capacity(_decimal(inputs.available_cash), cash_costs)
    counts = {
        "max_risk": shares_by_risk,
        "max_position": shares_by_allocation,
        "available_cash": shares_by_cash,
    }
    shares = min(counts.values())
    binding = [name for name, count in counts.items() if count == shares]
    capital_used = _total(shares, cash_costs)
    planned_loss = _total(shares, loss_costs)
    remaining_cash = _decimal(inputs.available_cash) - capital_used
    allocation_percent = None
    if _decimal(inputs.available_capital) > 0:
        allocation_percent = _ratio(capital_used / _decimal(inputs.available_capital) * Decimal(100))
    risk_per_share = planned_loss / shares if shares else max(loss_costs)
    reward = None if target is None else _decimal(shares) * _decimal(target) - capital_used
    risk_reward = reward / planned_loss if reward is not None and reward > 0 and planned_loss > 0 else None
    assumptions.append("All entry levels and the entry-cost assumption are included in cash, allocation, and planned-loss limits. Stop gaps and exit costs remain unmodeled.")

    if risk_reward is None:
        assumptions.append("Risk/reward is unavailable because the target, entry, and stop do not form a coherent payoff.")
    if shares == 0:
        assumptions.append("The binding limit buys fewer than one share.")

    scale_prices = inputs.scale_in_prices or ([entry] if entry else [])
    if inputs.scale_in_prices:
        assumptions.append(
            "Scale-in prices were entered in the dashboard. Shares are split evenly across those prices, with any remainder on the earliest prices."
        )
    elif entry is not None:
        assumptions.append("Only one entry price is known, so the plan has one limit and no entry zone.")

    exit_prices = inputs.take_profit_prices or ([target] if target else [])
    return {
        "status": "available",
        "reason": None,
        "shares": shares,
        "risk_per_share": _ratio(risk_per_share),
        "planned_loss": _money(planned_loss),
        "maximum_planned_loss": _money(planned_loss),
        "capital_used": _money(capital_used),
        "remaining_cash": _money(remaining_cash),
        "allocation_percent": allocation_percent,
        "risk_reward": None if risk_reward is None else _ratio(risk_reward),
        "binding_constraint": binding,
        "shares_by_risk": shares_by_risk,
        "shares_by_allocation": shares_by_allocation,
        "shares_by_cash": shares_by_cash,
        "direction": direction,
        "invalidation": invalidation,
        "limit_entries": _split(shares, scale_prices, price_source),
        "exits": _split(shares, exit_prices, exit_source),
        "entry_zone": zone,
        "assumptions": assumptions,
        "inputs": _input_echo(inputs),
    }


def _total(shares: int, costs: list[Decimal]) -> Decimal:
    base, extra = divmod(shares, len(costs))
    return sum(costs, Decimal(0)) * base + sum(costs[:extra], Decimal(0))


def _capacity(budget: Decimal, costs: list[Decimal]) -> int:
    """Largest even-split quantity whose actual level costs fit the limit."""
    low, high = 0, _whole_shares(budget / min(costs)) + 1
    while low + 1 < high:
        middle = (low + high) // 2
        if _total(middle, costs) <= budget:
            low = middle
        else:
            high = middle
    return low


def _missing_inputs(inputs: PositionInputs) -> list[str]:
    missing: list[str] = []
    if inputs.entry_price is None:
        missing.append("an entry price")
    if inputs.stop_loss is None:
        missing.append("a stop-loss price")
    if inputs.available_capital is None:
        missing.append("available capital")
    if inputs.available_cash is None:
        missing.append("available cash")
    if inputs.max_risk_amount is None and inputs.max_risk_percent is None:
        missing.append("maximum risk per trade")
    if inputs.max_position_percent is None:
        missing.append("maximum position allocation")
    return missing


def _invalidation(stop: float | None) -> dict:
    if stop is None:
        return {
            "status": "unavailable",
            "text": None,
            "stop_loss": None,
            "reason": "No stop-loss price was provided, so there is no invalidation price.",
        }
    return {
        "status": "available",
        "stop_loss": stop,
        "text": f"A trade through the stop price of {stop} invalidates this plan.",
        "reason": None,
    }


def _entry_zone(scale_prices: list[float], entry: float | None) -> dict:
    if len(scale_prices) >= 2:
        return {
            "status": "available",
            "low": min(scale_prices),
            "high": max(scale_prices),
            "source": "user",
            "reason": None,
        }
    if not scale_prices and entry is None:
        reason = "No entry price was supplied, so an entry zone was not created."
    else:
        reason = "Only one entry price is known, so an entry zone was not created."
    return {
        "status": "unavailable",
        "low": None,
        "high": None,
        "reason": reason,
    }


def _levels(entry: float | None, scale_prices: list[float], shares: int | None, source: str) -> list[dict]:
    prices = scale_prices or ([entry] if entry is not None else [])
    return _split(shares, prices, source)


def _exits(target: float | None, take_profits: list[float], shares: int | None, assumptions: list[str], source: str) -> list[dict]:
    if take_profits:
        assumptions.append(
            "Take-profit prices were entered in the dashboard. The share count is split evenly across them."
        )
        return _split(shares, take_profits, source)
    if target is not None:
        if source == "manual":
            assumptions.append("The target was typed in the manual calculator.")
        else:
            assumptions.append(
                "One research target was parsed. When a share count exists, the full quantity is assigned to that target because no partial-exit schedule was supplied."
            )
        return _split(shares, [target], source)
    assumptions.append("No take-profit price was supplied, so exit quantities are unavailable.")
    return []


def _direction(action: str | None, entry: Decimal, stop: Decimal) -> tuple[str, str | None]:
    inferred = "long" if stop < entry else "short"
    if action in {"Buy", "Overweight"} and inferred == "short":
        return inferred, "The action is a buy, but the stop is above the entry. Risk/reward is withheld."
    if action in {"Sell", "Underweight"} and inferred == "long":
        return inferred, "The action is a sell, but the stop is below the entry. Risk/reward is withheld."
    if action is None:
        side = "below" if inferred == "long" else "above"
        return inferred, f"No action label was parsed. Direction uses the stop sitting {side} the entry."
    return inferred, None


def _risk_reward(
    direction: str,
    action: str | None,
    entry: Decimal,
    stop: Decimal,
    target: float | None,
) -> Decimal | None:
    conflict = (
        (action in {"Buy", "Overweight"} and direction == "short")
        or (action in {"Sell", "Underweight"} and direction == "long")
    )
    if conflict or target is None:
        return None
    target_d = _decimal(target)
    if direction == "long" and target_d > entry and stop < entry:
        return (target_d - entry) / (entry - stop)
    if direction == "short" and target_d < entry and stop > entry:
        return (entry - target_d) / (stop - entry)
    return None


def _input_echo(inputs: PositionInputs) -> dict:
    return {
        "entry_price": inputs.entry_price,
        "stop_loss": inputs.stop_loss,
        "price_target": inputs.price_target,
        "action": inputs.action,
        "available_capital": inputs.available_capital,
        "available_cash": inputs.available_cash,
        "max_risk_amount": inputs.max_risk_amount,
        "max_risk_percent": inputs.max_risk_percent,
        "max_position_percent": inputs.max_position_percent,
        "cost_bps": inputs.cost_bps,
        "scale_in_prices": list(inputs.scale_in_prices),
        "take_profit_prices": list(inputs.take_profit_prices),
    }


def _unavailable_sizing(
    reason: str,
    assumptions: list[str],
    invalidation: dict,
    levels: list[dict],
    exits: list[dict],
    zone: dict,
    inputs: PositionInputs,
) -> dict:
    return {
        "status": "unavailable",
        "reason": reason,
        "shares": None,
        "risk_per_share": None,
        "planned_loss": None,
        "maximum_planned_loss": None,
        "capital_used": None,
        "remaining_cash": None,
        "allocation_percent": None,
        "risk_reward": None,
        "binding_constraint": [],
        "shares_by_risk": None,
        "shares_by_allocation": None,
        "shares_by_cash": None,
        "direction": None,
        "invalidation": invalidation,
        "limit_entries": levels,
        "exits": exits,
        "entry_zone": zone,
        "assumptions": assumptions,
        "inputs": _input_echo(inputs),
    }


def assemble_trade_plan(
    *,
    ticker: str,
    analysis_date: str,
    reports: dict | None,
    reference: dict,
    preferences: dict,
    price_inputs: dict | None = None,
    plan_version: int | None = None,
    input_snapshot: dict | None = None,
) -> dict:
    """Combine verified market data, parsed hypotheses, and the position calculation."""
    reports = reports or {}
    hypotheses = extract_hypotheses(
        reports.get("trader_investment_plan"),
        reports.get("final_trade_decision"),
        reports.get("investment_plan"),
    )
    preferences = preferences or {}
    prices = price_inputs or {}
    inputs = PositionInputs(
        entry_price=hypotheses["entry_price"],
        stop_loss=hypotheses["stop_loss"],
        price_target=hypotheses["price_target"],
        action=hypotheses["action"],
        available_capital=preferences.get("available_capital"),
        available_cash=preferences.get("available_cash"),
        max_risk_amount=preferences.get("max_risk_amount"),
        max_risk_percent=preferences.get("max_risk_percent"),
        max_position_percent=preferences.get("max_position_percent"),
        cost_bps=preferences.get("cost_bps") or 0,
        scale_in_prices=list(prices.get("scale_in_prices") or []),
        take_profit_prices=list(prices.get("take_profit_prices") or []),
    )
    if hypotheses.get("plan_status") != "ready" or hypotheses.get("final_status") != "parsed":
        reason = hypotheses.get("plan_reason") or hypotheses.get("result_reason") or (
            "The final decision needs review, so no share count was calculated."
        )
        sizing = _unavailable_sizing(
            reason,
            [
                "Share count, planned loss, and capital use are calculated in Python.",
                "A conditional or unparsed final decision does not become an unconditional order.",
            ],
            _invalidation(hypotheses["stop_loss"]),
            _levels(inputs.entry_price, inputs.scale_in_prices, None, "research_hypothesis"),
            _exits(inputs.price_target, inputs.take_profit_prices, None, [], "research_hypothesis"),
            _entry_zone(inputs.scale_in_prices, inputs.entry_price),
            inputs,
        )
    else:
        sizing = calculate_position(inputs)
    evidence = [
        {
            "label": "Reference close",
            "source": "yfinance",
            "status": reference.get("status") or "unavailable",
            "detail": reference.get("error") or _reference_detail(reference),
        },
        {
            "label": "Entry price",
            "source": "Trader proposal",
            "status": _evidence_status(hypotheses, "entry_price"),
            "detail": _price_field_detail(hypotheses, "entry_price"),
        },
        {
            "label": "Stop loss",
            "source": "Trader proposal",
            "status": _evidence_status(hypotheses, "stop_loss"),
            "detail": _price_field_detail(hypotheses, "stop_loss"),
        },
        {
            "label": "Price target",
            "source": "Portfolio manager decision",
            "status": _evidence_status(hypotheses, "price_target"),
            "detail": _price_field_detail(hypotheses, "price_target"),
        },
    ]
    explanation = _explanation(hypotheses, sizing)
    return {
        "ticker": ticker,
        "analysis_date": analysis_date,
        "disclaimer": DISCLAIMER,
        "orders_sent": False,
        "limitations": LIMITATIONS,
        "verified_market": reference,
        "hypotheses": hypotheses,
        "entry_zone": sizing["entry_zone"],
        "limit_entries": sizing["limit_entries"],
        "exits": sizing["exits"],
        "invalidation": sizing["invalidation"],
        "sizing": {key: value for key, value in sizing.items() if key not in {"limit_entries", "exits", "entry_zone", "invalidation"}},
        "assumptions": sizing["assumptions"],
        "explanation": explanation,
        "evidence": evidence,
        "calculated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "plan_version": plan_version,
        "input_snapshot": input_snapshot,
    }


def _reference_detail(reference: dict) -> str | None:
    price = reference.get("price")
    bar_date = reference.get("bar_date")
    if price is None:
        return None
    return f"Close {float(price):.2f} on {bar_date}"


def _evidence_status(hypotheses: dict, name: str) -> str:
    state = (hypotheses.get("price_fields") or {}).get(name)
    if state == "available":
        return "available"
    if state == "stated_absent":
        return "not_provided"
    if state == "unreadable":
        return "unreadable"
    return "unavailable"


def _price_field_detail(hypotheses: dict, name: str) -> str | None:
    state = (hypotheses.get("price_fields") or {}).get(name)
    if state == "stated_absent":
        return "The report states this price is not provided."
    if state == "unreadable":
        return "The labeled value was not one positive number."
    if state == "missing":
        return "No labeled price was saved."
    return None


def _explanation(hypotheses: dict, sizing: dict) -> str:
    if sizing["status"] != "available":
        return (
            "The share count was not calculated. "
            + (sizing["reason"] or "Required inputs are missing.")
            + " Hypothesis prices are shown only when a labeled field parsed as a single positive number."
        )
    shares = sizing["shares"]
    binding = ", ".join(sizing["binding_constraint"]) or "the inputs"
    return (
        f"The calculated size is {shares} share(s), limited by {binding}. "
        "The entry and stop used in that arithmetic are research hypotheses, not verified fills. "
        "Planned loss sums each entry quantity times its distance to the stop, plus assumed entry costs. It is not a guaranteed maximum loss."
    )
