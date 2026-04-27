"""
stock_agent.py - Financial analysis agent (uses Claude Opus for all analysis)
"""
import logging
import asyncio
from typing import Optional
from llm import chat

logger = logging.getLogger(__name__)


class StockAgent:
    def __init__(self, memory=None):
        self.memory = memory

    def _fetch_fundamentals(self, ticker: str) -> dict:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            info = t.info or {}
            hist = t.history(period="1y")
            return {
                "info": {k: info.get(k) for k in [
                    "longName", "sector", "industry", "marketCap", "trailingPE",
                    "priceToBook", "debtToEquity", "currentRatio", "returnOnEquity",
                    "revenueGrowth", "earningsGrowth", "dividendYield",
                    "freeCashflow", "operatingMargins", "profitMargins",
                    "52WeekChange", "currentPrice", "targetMeanPrice",
                    "recommendationMean", "numberOfAnalystOpinions",
                ]},
                "price_history": hist["Close"].tail(60).to_dict() if not hist.empty else {},
            }
        except Exception as e:
            return {"error": str(e)}

    def _fetch_news(self, ticker: str) -> list[str]:
        try:
            import feedparser
            feeds = [
                f"https://finance.yahoo.com/rss/headline?s={ticker}",
                "https://feeds.reuters.com/reuters/businessNews",
            ]
            items = []
            for url in feeds:
                feed = feedparser.parse(url)
                for entry in feed.entries[:3]:
                    items.append(f"{entry.get('title', '')} — {entry.get('summary', '')[:200]}")
            return items[:6]
        except Exception as e:
            return [f"News fetch error: {e}"]

    def _technical_analysis(self, ticker: str) -> dict:
        try:
            import yfinance as yf
            import pandas as pd
            hist = yf.Ticker(ticker).history(period="1y")
            if hist.empty:
                return {}
            close = hist["Close"]
            volume = hist["Volume"]

            ma50 = close.rolling(50).mean().iloc[-1]
            ma200 = close.rolling(200).mean().iloc[-1]
            current = close.iloc[-1]

            # RSI
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] != 0 else 100
            rsi = 100 - (100 / (1 + rs))

            # MACD
            ema12 = close.ewm(span=12).mean()
            ema26 = close.ewm(span=26).mean()
            macd = (ema12 - ema26).iloc[-1]
            signal = (ema12 - ema26).ewm(span=9).mean().iloc[-1]

            return {
                "current_price": round(current, 2),
                "ma_50": round(ma50, 2),
                "ma_200": round(ma200, 2),
                "above_50ma": current > ma50,
                "above_200ma": current > ma200,
                "rsi_14": round(rsi, 1),
                "macd": round(macd, 4),
                "macd_signal": round(signal, 4),
                "macd_bullish": macd > signal,
                "avg_volume_30d": int(volume.tail(30).mean()),
                "price_52w_high": round(close.tail(252).max(), 2),
                "price_52w_low": round(close.tail(252).min(), 2),
            }
        except Exception as e:
            return {"error": str(e)}

    async def analyse(self, ticker: str, analysis_type: str = "full") -> str:
        ticker = ticker.upper().strip()
        logger.info(f"[StockAgent] Analysing {ticker} ({analysis_type})")

        fund = self._fetch_fundamentals(ticker)
        tech = self._technical_analysis(ticker)
        news = self._fetch_news(ticker)

        prompt = f"""Perform a {analysis_type} analysis of {ticker}.

FUNDAMENTAL DATA:
{fund}

TECHNICAL DATA:
{tech}

RECENT NEWS:
{chr(10).join(news)}

Provide a structured analysis covering:
1. Business overview
2. Fundamental health (valuation, profitability, balance sheet)
3. Technical picture (trend, momentum, key levels)
4. News sentiment (last 7 days)
5. Key risks
6. Summary verdict (bullish/bearish/neutral with reasoning)

Be specific with numbers. Note: ASX stocks use .AX suffix (e.g., BHP.AX).
Do NOT include financial advice disclaimers in the written report."""

        result = chat([{"role": "user", "content": prompt}], tier=3)
        report = result["content"]

        disclaimer = "\n\nThis is research only, not financial advice, sir."
        full_report = report + disclaimer

        if self.memory:
            self.memory.add_note(
                title=f"Stock Analysis: {ticker}",
                content=full_report,
                topic="stocks",
                tags=f"stocks,{ticker}"
            )

        return full_report
