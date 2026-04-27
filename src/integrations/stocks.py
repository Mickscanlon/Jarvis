"""
stocks.py - Market data fetching (yfinance + Alpha Vantage free tier)
"""
import os
import logging
from typing import Optional
from dotenv import load_dotenv

load_dotenv(dotenv_path="C:/Users/micha/jarvis/.env")
logger = logging.getLogger(__name__)

AV_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")


def get_quote(ticker: str) -> dict:
    """Get current price and basic quote data."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info
        hist = t.history(period="2d")
        if hist.empty:
            return {"error": f"No data for {ticker}"}

        current = hist["Close"].iloc[-1]
        prev = hist["Close"].iloc[-2] if len(hist) >= 2 else current
        change = current - prev
        change_pct = (change / prev) * 100 if prev else 0

        return {
            "ticker": ticker,
            "price": round(current, 3),
            "change": round(change, 3),
            "change_pct": round(change_pct, 2),
            "currency": info.get("currency", "AUD"),
            "name": info.get("longName", ticker),
            "market_cap": info.get("marketCap"),
        }
    except Exception as e:
        return {"error": str(e)}


def get_price_history(ticker: str, period: str = "3mo") -> dict:
    """Get historical prices for a ticker."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=period)
        if hist.empty:
            return {"error": "No data"}
        return {
            "dates": [str(d.date()) for d in hist.index],
            "closes": [round(c, 3) for c in hist["Close"].tolist()],
            "volumes": hist["Volume"].tolist(),
        }
    except Exception as e:
        return {"error": str(e)}


def get_portfolio_value(holdings: list[dict]) -> dict:
    """Calculate current portfolio value."""
    total_value = 0
    total_cost = 0
    positions = []

    for h in holdings:
        quote = get_quote(h["ticker"])
        if "error" not in quote:
            current_price = quote["price"]
            units = h["units"]
            avg_price = h["avg_buy_price"]
            position_value = current_price * units
            position_cost = avg_price * units
            gain_loss = position_value - position_cost
            gain_pct = (gain_loss / position_cost) * 100 if position_cost else 0

            positions.append({
                "ticker": h["ticker"],
                "units": units,
                "current_price": current_price,
                "avg_buy_price": avg_price,
                "value": round(position_value, 2),
                "gain_loss": round(gain_loss, 2),
                "gain_pct": round(gain_pct, 2),
                "day_change_pct": quote["change_pct"],
            })
            total_value += position_value
            total_cost += position_cost

    total_gain = total_value - total_cost
    return {
        "positions": positions,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_gain_loss": round(total_gain, 2),
        "total_return_pct": round((total_gain / total_cost) * 100, 2) if total_cost else 0,
    }


def format_quote_voice(ticker: str) -> str:
    """Format a quote for voice delivery."""
    q = get_quote(ticker)
    if "error" in q:
        return f"Couldn't fetch {ticker}, sir. {q['error']}"
    direction = "up" if q["change_pct"] >= 0 else "down"
    return (f"{q.get('name', ticker)} is trading at {q['currency']} {q['price']:.2f}, "
            f"{direction} {abs(q['change_pct']):.1f}% today.")
