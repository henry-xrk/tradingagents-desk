"""Pydantic models for dashboard requests."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AnalystId = Literal["market", "social", "news", "fundamentals"]


def _positive_prices(values: list[float]) -> list[float]:
    cleaned: list[float] = []
    for value in values:
        if value <= 0:
            raise ValueError("prices must be positive")
        if value not in cleaned:
            cleaned.append(value)
    return cleaned


class AnalysisCreate(BaseModel):
    ticker: str
    analysis_date: str
    analysts: list[AnalystId] = Field(min_length=1)
    research_depth: Literal[1, 3, 5] = 1
    output_language: Literal["English", "Chinese"] = "English"
    llm_provider: str = "openai"
    quick_think_llm: str
    deep_think_llm: str
    backend_url: str | None = None

    @field_validator("ticker", "llm_provider", "quick_think_llm", "deep_think_llm")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be blank")
        return text

    @field_validator("analysis_date")
    @classmethod
    def _strip_date(cls, value: str) -> str:
        return value.strip()

    @field_validator("backend_url")
    @classmethod
    def _optional_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        if not text.startswith(("http://", "https://")):
            raise ValueError("backend_url must start with http:// or https://")
        return text


class CapitalPreferences(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    available_capital: float | None = None
    available_cash: float | None = None
    max_risk_amount: float | None = None
    max_risk_percent: float | None = None
    max_position_percent: float | None = None
    cost_bps: float = 0

    @field_validator("available_capital", "available_cash", "max_risk_amount")
    @classmethod
    def _non_negative(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("amounts must be zero or greater")
        return value

    @field_validator("max_risk_percent", "max_position_percent")
    @classmethod
    def _percent(cls, value: float | None) -> float | None:
        if value is not None and (value < 0 or value > 100):
            raise ValueError("percent must be between 0 and 100")
        return value

    @field_validator("cost_bps")
    @classmethod
    def _cost(cls, value: float) -> float:
        if value < 0 or value > 10000:
            raise ValueError("cost_bps must be between 0 and 10000")
        return value


class PlanPrices(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    scale_in_prices: list[float] = Field(default_factory=list)
    take_profit_prices: list[float] = Field(default_factory=list)

    @field_validator("scale_in_prices", "take_profit_prices")
    @classmethod
    def _prices(cls, value: list[float]) -> list[float]:
        return _positive_prices(value)


class TradePlanUpdate(CapitalPreferences, PlanPrices):
    pass


class PositionSizeRequest(CapitalPreferences, PlanPrices):
    entry_price: float | None = None
    stop_loss: float | None = None
    price_target: float | None = None
    action: str | None = None

    @field_validator("entry_price", "stop_loss", "price_target")
    @classmethod
    def _optional_price(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("prices must be positive")
        return value

    @field_validator("action")
    @classmethod
    def _action(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class ValidateRequest(BaseModel):
    confirm_charge: bool = False


class WatchlistAdd(BaseModel):
    ticker: str

    @field_validator("ticker")
    @classmethod
    def _ticker(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("ticker must not be blank")
        return text
