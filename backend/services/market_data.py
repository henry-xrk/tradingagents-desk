"""Yahoo Finance candles through the installed data loader.

Prices come from ``load_ohlcv``. A failure stays an error. Nothing in this
module substitutes a simulated series.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from backend.errors import public_exception
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.default_config import DEFAULT_CONFIG

INDICATORS = (
    ("close_20_sma", "sma20"),
    ("close_50_sma", "sma50"),
    ("close_200_sma", "sma200"),
    ("rsi", "rsi"),
    ("macd", "macd"),
    ("macds", "macd_signal"),
    ("macdh", "macd_histogram"),
)


class MarketDataError(Exception):
    def __init__(self, message: str, *, code: str = "market_data"):
        super().__init__(message)
        self.message = message
        self.code = code
        self.fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat()


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _clean(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        return None
    number = float(value)
    if number != number:  # NaN
        return None
    return number


def _day(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_localize(None)
    return stamp.strftime("%Y-%m-%d")


def load_chart(ticker: str, as_of: str, *, include_candles: bool = True, loader=None) -> dict:
    """Return verified OHLCV and indicators for one symbol."""
    fetch = loader or _default_loader
    download_started_at = _now()
    try:
        frame = fetch(ticker, as_of)
    except NoMarketDataError as exc:
        raise MarketDataError(str(exc), code="no_market_data") from exc
    except MarketDataError:
        raise
    except Exception as exc:
        raise MarketDataError(public_exception(exc), code="market_data") from exc
    fetched_at = _now()

    if frame is None or getattr(frame, "empty", True):
        raise MarketDataError(f"No market data for {ticker!r}.", code="no_market_data")

    data = frame.copy()
    if "Date" not in data.columns:
        raise MarketDataError(
            f"Yahoo data for {ticker!r} did not include a Date column.",
            code="market_data",
        )
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])
    data = data[data["Date"] <= pd.Timestamp(as_of)].sort_values("Date")
    if data.empty:
        raise MarketDataError(
            f"No Yahoo rows for {ticker!r} on or before {as_of}.",
            code="no_market_data",
        )

    indicators, indicator_error = _indicators(data)
    candles = []
    for index, (_, row) in enumerate(data.iterrows()):
        point = {
            "time": _day(row["Date"]),
            "open": _clean(row.get("Open")),
            "high": _clean(row.get("High")),
            "low": _clean(row.get("Low")),
            "close": _clean(row.get("Close")),
            "volume": _volume(row.get("Volume")),
        }
        for _source, public in INDICATORS:
            point[public] = _at(indicators.get(public), index)
        if point["time"] and point["close"] is not None:
            candles.append(point)

    if not candles:
        raise MarketDataError(
            f"Yahoo rows for {ticker!r} had no usable closes.",
            code="no_market_data",
        )

    last = candles[-1]
    previous = candles[-2]["close"] if len(candles) > 1 else None
    change = None if previous is None else last["close"] - previous
    change_percent = None
    if change is not None and previous not in (None, 0):
        change_percent = change / previous * 100

    session = _session(last["time"])
    currency = _currency(data)
    payload = {
        "ok": True,
        "symbol": ticker,
        "as_of": as_of,
        "source": "yfinance",
        "download_started_at": download_started_at,
        "fetched_at": fetched_at,
        "response_at": _now(),
        "bar_date": last["time"],
        "bar_matches_as_of": last["time"] == as_of,
        "reference_price": last["close"],
        "previous_close": previous,
        "change": change,
        "change_percent": change_percent,
        "currency": currency,
        "timezone": None,
        "cache_age_seconds": None,
        "cache_status": "unknown",
        "bar_complete": session["bar_complete"],
        "session": session["session"],
        "session_note": session["note"],
        "indicators_error": indicator_error,
        "indicator_note": "SMA, RSI, and MACD are calculated with stockstats from the Yahoo closes. Missing values are omitted.",
    }
    if include_candles:
        payload["candles"] = candles
    else:
        payload["candles"] = []
    return payload


def reference_quote(ticker: str, as_of: str) -> dict:
    """The latest close, or an explicit unavailable record. Never a fake price."""
    try:
        chart = load_chart(ticker, as_of, include_candles=False)
    except MarketDataError as exc:
        return {
            "status": "unavailable",
            "source": "yfinance",
            "symbol": ticker,
            "as_of": as_of,
            "price": None,
            "bar_date": None,
            "fetched_at": exc.fetched_at,
            "previous_close": None,
            "change": None,
            "change_percent": None,
            "error": exc.message,
        }
    return {
        "status": "available",
        "source": "yfinance",
        "symbol": chart["symbol"],
        "as_of": as_of,
        "price": chart["reference_price"],
        "bar_date": chart["bar_date"],
        "fetched_at": chart["fetched_at"],
        "previous_close": chart["previous_close"],
        "change": chart["change"],
        "change_percent": chart["change_percent"],
        "error": None,
    }


def quote_summary(ticker: str, as_of: str) -> dict:
    try:
        chart = load_chart(ticker, as_of, include_candles=False)
    except MarketDataError as exc:
        return {
            "ticker": ticker,
            "ok": False,
            "source": "yfinance",
            "error": exc.message,
            "code": exc.code,
            "fetched_at": exc.fetched_at,
        }
    return {
        "ticker": chart["symbol"],
        "ok": True,
        "source": "yfinance",
        "price": chart["reference_price"],
        "previous_close": chart["previous_close"],
        "change": chart["change"],
        "change_percent": chart["change_percent"],
        "bar_date": chart["bar_date"],
        "fetched_at": chart["fetched_at"],
        "as_of": as_of,
        "error": None,
    }


def _session(bar_date: str | None) -> dict:
    """A daily bar dated today is not treated as a closed session."""
    from tradingagents.dataflows.date_window import get_current_date

    if not bar_date:
        return {"bar_complete": None, "session": "unknown", "note": "The bar date is unknown."}
    today = get_current_date()
    if bar_date == today:
        return {
            "bar_complete": False,
            "session": "incomplete",
            "note": "This daily bar is dated today and is not marked as closed.",
        }
    if bar_date < today:
        return {"bar_complete": True, "session": "closed", "note": None}
    return {"bar_complete": None, "session": "unknown", "note": "The session state is unknown."}


def _currency(frame: pd.DataFrame):
    if "Currency" not in frame.columns or frame.empty:
        return None
    value = frame["Currency"].iloc[-1]
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _default_loader(ticker: str, as_of: str):
    from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv

    with run_config(DEFAULT_CONFIG):
        return load_ohlcv(ticker, as_of, fill_gaps=False)


def _indicators(frame: pd.DataFrame) -> tuple[dict, str | None]:
    try:
        from stockstats import wrap
    except Exception as exc:  # pragma: no cover - stockstats is installed with the engine
        return {}, public_exception(exc)
    try:
        wrapped = wrap(frame.copy())
    except Exception as exc:
        return {}, public_exception(exc)
    columns: dict = {}
    errors: list[str] = []
    for source, public in INDICATORS:
        try:
            series = wrapped[source]
        except Exception as exc:
            errors.append(f"{public}: {type(exc).__name__}")
            continue
        if len(series) != len(frame):
            errors.append(f"{public}: length mismatch")
            continue
        columns[public] = series
    return columns, "; ".join(errors) or None


def _at(series, index: int):
    if series is None:
        return None
    try:
        return _clean(series.iloc[index])
    except Exception:
        return None


def _volume(value):
    number = _clean(value)
    if number is None:
        return None
    if number.is_integer():
        return int(number)
    return number
