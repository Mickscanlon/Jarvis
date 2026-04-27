"""
scheduler.py - Background task scheduler for proactive JARVIS features
"""
import os
import asyncio
import logging
from datetime import datetime, time as dtime

logger = logging.getLogger(__name__)

MORNING_BRIEFING_TIME = dtime(7, 30)
MARKET_OPEN_TIME = dtime(10, 0)
EVENING_SUMMARY_TIME = dtime(18, 0)


class Scheduler:
    def __init__(self, memory):
        self.memory = memory
        self._last_morning = None
        self._last_market = None
        self._last_evening = None

    async def run(self):
        """Main scheduler loop — checks every 60 seconds."""
        logger.info("[Scheduler] Started")
        while True:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"[Scheduler] Error: {e}")
            await asyncio.sleep(60)

    async def _tick(self):
        now = datetime.now()
        today = now.date()
        t = now.time()

        if (t.hour == MORNING_BRIEFING_TIME.hour and t.minute == MORNING_BRIEFING_TIME.minute
                and self._last_morning != today):
            self._last_morning = today
            await self._morning_briefing()

        if (t.hour == MARKET_OPEN_TIME.hour and t.minute == MARKET_OPEN_TIME.minute
                and now.weekday() < 5 and self._last_market != today):
            self._last_market = today
            await self._market_check()

        if (t.hour == EVENING_SUMMARY_TIME.hour and t.minute == EVENING_SUMMARY_TIME.minute
                and self._last_evening != today):
            self._last_evening = today
            await self._evening_summary()

        # Run any scheduled tasks from DB
        await self._run_db_scheduled_tasks()

    async def _morning_briefing(self):
        from agents.researcher import ResearchAgent
        from integrations.news import get_morning_briefing

        logger.info("[Scheduler] Morning briefing")
        try:
            import httpx
            location = os.getenv("USER_LOCATION", "Bendigo, Victoria")
            weather_resp = await asyncio.to_thread(
                lambda: httpx.get(f"https://wttr.in/{location.replace(' ', '+')}?format=3", timeout=5).text
            )
        except Exception:
            weather_resp = "(weather unavailable)"

        tasks = self.memory.get_tasks("open")
        task_summary = "\n".join(
            f"- [{t['priority']}] {t['title']}" for t in tasks[:5]
        ) if tasks else "No open tasks."

        news = get_morning_briefing(self.memory)
        usage = self.memory.get_usage_stats()

        briefing = (
            f"Good morning, sir. "
            f"Weather in {os.getenv('USER_LOCATION', 'Bendigo')}: {weather_resp}. "
            f"You have {len(tasks)} open task{'s' if len(tasks) != 1 else ''}. "
            f"Top priority: {tasks[0]['title'] if tasks else 'none'}. "
            f"{news.get('summary', 'No news available.')} "
            f"API spend so far today: ${usage['today']['cost_aud']:.4f} AUD."
        )

        await _broadcast({"type": "notification", "title": "Morning Briefing",
                          "body": briefing, "priority": "low"})
        await _speak(briefing)

    async def _market_check(self):
        portfolio = self._get_portfolio()
        if not portfolio:
            return

        logger.info("[Scheduler] Market check")
        alerts = []
        for holding in portfolio:
            try:
                import yfinance as yf
                hist = yf.Ticker(holding["ticker"]).history(period="2d")
                if len(hist) >= 2:
                    prev_close = hist["Close"].iloc[-2]
                    current = hist["Close"].iloc[-1]
                    change_pct = ((current - prev_close) / prev_close) * 100
                    if abs(change_pct) > 5:
                        direction = "up" if change_pct > 0 else "down"
                        alerts.append(f"{holding['ticker']} is {direction} {abs(change_pct):.1f}%")
            except Exception:
                pass

        if alerts:
            msg = f"Market alert, sir. {', '.join(alerts)}."
            await _broadcast({"type": "notification", "title": "Portfolio Alert",
                              "body": msg, "priority": "medium"})
            await _speak(msg)

    async def _evening_summary(self):
        tasks_done = self.memory.get_tasks("completed")
        today_done = [
            t for t in tasks_done
            if t.get("completed_at", "").startswith(datetime.now().strftime("%Y-%m-%d"))
        ]
        tasks_open = self.memory.get_tasks("open")
        usage = self.memory.get_usage_stats()

        summary = (
            f"Evening summary, sir. "
            f"You completed {len(today_done)} task{'s' if len(today_done) != 1 else ''} today. "
            f"{len(tasks_open)} tasks remain open. "
            f"Today's AI spend: ${usage['today']['cost_aud']:.4f} AUD."
        )
        await _speak(summary)

    def _get_portfolio(self) -> list:
        try:
            import sqlite3
            from memory import DB_PATH
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute("SELECT ticker, units, avg_buy_price FROM portfolio").fetchall()
            conn.close()
            return [{"ticker": r[0], "units": r[1], "avg_buy_price": r[2]} for r in rows]
        except Exception:
            return []

    async def _run_db_scheduled_tasks(self):
        try:
            import sqlite3, json
            from memory import DB_PATH
            conn = sqlite3.connect(DB_PATH)
            now = datetime.now().isoformat()
            rows = conn.execute(
                "SELECT id, name, task_type, task_config FROM scheduled_tasks "
                "WHERE enabled=1 AND (next_run IS NULL OR next_run <= ?)", (now,)
            ).fetchall()
            conn.close()

            for row in rows:
                task_id, name, task_type, config_str = row
                config = json.loads(config_str or "{}")
                logger.info(f"[Scheduler] Running task: {name}")
                # Update last_run
                conn = sqlite3.connect(DB_PATH)
                conn.execute("UPDATE scheduled_tasks SET last_run=? WHERE id=?", (now, task_id))
                conn.commit()
                conn.close()
        except Exception as e:
            logger.error(f"[Scheduler] DB task error: {e}")


async def _speak(text: str):
    """Broadcast speech to all connected WS clients."""
    try:
        from server import speak_and_broadcast
        await speak_and_broadcast(text)
    except Exception:
        pass


async def _broadcast(msg: dict):
    try:
        from server import broadcast
        await broadcast(msg)
    except Exception:
        pass
