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


def extract_hypotheses(trader_text: str | None, decision_text: str | None) -> dict:
    """Prices from the labeled trader and portfolio-manager lines only."""
    entry = parse_labeled_price(trader_text, "Entry Price")
    stop = parse_labeled_price(trader_text, "Stop Loss")
    target = parse_labeled_price(decision_text, "Price Target")
    action = _label_value(trader_text, "Action")
    rating = _label_value(decision_text, "Rating")
    missing = [
        name
        for name, value in (
            ("entry_price", entry),
            ("stop_loss", stop),
            ("price_target", target),
        )
        if value is None
    ]
    if missing and (entry is None and stop is None and target is None):
        status = "unavailable"
    elif missing:
        status = "partial"
    else:
        status = "available"
    return {
        "status": status,
        "source": "generated_research",
        "action": action,
        "rating": rating,
        "entry_price": entry,
        "stop_loss": stop,
        "price_target": target,
        "missing": missing,
    }


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
    levels = _levels(entry, inputs.scale_in_prices, None)
    exits = _exits(target, inputs.take_profit_prices, None, assumptions)
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

    price_source = "user" if inputs.scale_in_prices else "research_hypothesis"
    scale_prices = inputs.scale_in_prices or ([entry] if entry else [])
    if inputs.scale_in_prices:
        assumptions.append(
            "Scale-in prices were entered in the dashboard. Shares are split evenly across those prices, with any remainder on the earliest prices."
        )
    elif entry is not None:
        assumptions.append("Only one entry price is known, so the plan has one limit and no entry zone.")

    exit_source = "user" if inputs.take_profit_prices else "research_hypothesis"
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


def _levels(entry: float | None, scale_prices: list[float], shares: int | None) -> list[dict]:
    prices = scale_prices or ([entry] if entry is not None else [])
    source = "user" if scale_prices else "research_hypothesis"
    return _split(shares, prices, source)


def _exits(target: float | None, take_profits: list[float], shares: int | None, assumptions: list[str]) -> list[dict]:
    if take_profits:
        assumptions.append(
            "Take-profit prices were entered in the dashboard. The share count is split evenly across them."
        )
        return _split(shares, take_profits, "user")
    if target is not None:
        assumptions.append(
            "One research target was parsed. When a share count exists, the full quantity is assigned to that target because no partial-exit schedule was supplied."
        )
        return _split(shares, [target], "research_hypothesis")
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
    )
    preferences = preferences or {}
    prices = price_inputs or {}
    sizing = calculate_position(
        PositionInputs(
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
    )
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
            "status": "available" if hypotheses["entry_price"] is not None else "unavailable",
        },
        {
            "label": "Stop loss",
            "source": "Trader proposal",
            "status": "available" if hypotheses["stop_loss"] is not None else "unavailable",
        },
        {
            "label": "Price target",
            "source": "Portfolio manager decision",
            "status": "available" if hypotheses["price_target"] is not None else "unavailable",
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
    return f"Close {price} on {bar_date}"


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
