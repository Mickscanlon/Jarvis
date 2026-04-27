"""
memory.py - Three-tier memory system: in-context + session summary + persistent SQLite
"""
import os
import json
import sqlite3
import numpy as np
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

load_dotenv(dotenv_path="C:/Users/micha/jarvis/.env")

DB_PATH = os.getenv("MEMORY_DB", "C:/Users/micha/jarvis/memory/jarvis.db")


class Memory:
    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        print("[Memory] Loading embedding model...")
        from sentence_transformers import SentenceTransformer
        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
        self._init_db()
        print("[Memory] Ready.")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        conn = self._conn()
        c = conn.cursor()

        # Legacy memories table (keep for backward compat / embeddings)
        c.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT DEFAULT 'fact',
                content TEXT NOT NULL,
                source TEXT DEFAULT 'conversation',
                importance INTEGER DEFAULT 5,
                embedding BLOB,
                created_at TEXT NOT NULL,
                last_accessed TEXT,
                access_count INTEGER DEFAULT 0
            )
        """)

        # Tasks
        c.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'open',
                due_date TEXT,
                due_time TEXT,
                project TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)

        # Notes
        c.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                topic TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Style profile (learning user preferences)
        c.execute("""
            CREATE TABLE IF NOT EXISTS style_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                updated_at TEXT NOT NULL,
                UNIQUE(category, key)
            )
        """)

        # Usage / cost log
        c.execute("""
            CREATE TABLE IF NOT EXISTS usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                date TEXT NOT NULL,
                model TEXT NOT NULL,
                tier INTEGER DEFAULT 0,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_aud REAL DEFAULT 0.0,
                task_type TEXT DEFAULT '',
                duration_ms INTEGER DEFAULT 0
            )
        """)

        # Scheduled tasks
        c.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                cron_expression TEXT NOT NULL,
                last_run TEXT,
                next_run TEXT,
                enabled INTEGER DEFAULT 1,
                task_type TEXT NOT NULL,
                task_config TEXT DEFAULT '{}'
            )
        """)

        # Portfolio holdings
        c.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL UNIQUE,
                units REAL NOT NULL,
                avg_buy_price REAL NOT NULL,
                currency TEXT DEFAULT 'AUD',
                added_at TEXT NOT NULL
            )
        """)

        # Budget
        c.execute("""
            CREATE TABLE IF NOT EXISTS budget_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                category_type TEXT NOT NULL,
                monthly_target REAL DEFAULT 0.0
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                direction TEXT NOT NULL,
                description TEXT DEFAULT '',
                date TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # FTS5 virtual tables for fast text search
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
            USING fts5(content, content='memories', content_rowid='id')
        """)
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS task_fts
            USING fts5(title, description, content='tasks', content_rowid='id')
        """)
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS note_fts
            USING fts5(title, content, topic, content='notes', content_rowid='id')
        """)

        conn.commit()
        conn.close()

    def _embed(self, text: str) -> np.ndarray:
        return self.embedder.encode(text, normalize_embeddings=True)

    # ── Memories ──────────────────────────────────────────────────────────────

    def add_memory(self, content: str, source: str = "conversation",
                   mem_type: str = "fact", importance: int = 5) -> int:
        embedding = self._embed(content)
        now = datetime.now().isoformat()
        conn = self._conn()
        c = conn.execute(
            "INSERT INTO memories (type, content, source, importance, embedding, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (mem_type, content, source, importance, embedding.tobytes(), now)
        )
        row_id = c.lastrowid
        conn.execute("INSERT INTO memory_fts(rowid, content) VALUES (?, ?)", (row_id, content))
        conn.commit()
        conn.close()
        return row_id

    def search_memories(self, query: str, top_k: int = 5) -> list[str]:
        # Semantic search via embeddings
        query_emb = self._embed(query)
        conn = self._conn()
        rows = conn.execute("SELECT id, content, embedding FROM memories").fetchall()
        conn.close()

        if not rows:
            return []

        scored = []
        for row in rows:
            emb = np.frombuffer(row["embedding"], dtype=np.float32)
            score = float(np.dot(query_emb, emb))
            scored.append((score, row["content"]))

        scored.sort(reverse=True)
        return [c for _, c in scored[:top_k] if _ > 0.25]

    def get_context_for(self, query: str) -> str:
        memories = self.search_memories(query, top_k=5)
        if not memories:
            return ""
        lines = "\n".join(f"- {m}" for m in memories)
        return f"\nRelevant context from past sessions:\n{lines}\n"

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def add_task(self, title: str, description: str = "", priority: str = "medium",
                 due_date: str = None, project: str = "") -> int:
        now = datetime.now().isoformat()
        conn = self._conn()
        c = conn.execute(
            "INSERT INTO tasks (title, description, priority, due_date, project, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (title, description, priority, due_date, project, now)
        )
        row_id = c.lastrowid
        conn.execute("INSERT INTO task_fts(rowid, title, description) VALUES (?, ?, ?)",
                     (row_id, title, description))
        conn.commit()
        conn.close()
        return row_id

    def get_tasks(self, status: str = "open") -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY "
            "CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 "
            "WHEN 'medium' THEN 3 ELSE 4 END, created_at",
            (status,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def complete_task(self, task_id: int):
        conn = self._conn()
        conn.execute(
            "UPDATE tasks SET status='completed', completed_at=? WHERE id=?",
            (datetime.now().isoformat(), task_id)
        )
        conn.commit()
        conn.close()

    # ── Notes ─────────────────────────────────────────────────────────────────

    def add_note(self, title: str, content: str, topic: str = "", tags: str = "") -> int:
        now = datetime.now().isoformat()
        conn = self._conn()
        c = conn.execute(
            "INSERT INTO notes (title, content, topic, tags, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (title, content, topic, tags, now, now)
        )
        row_id = c.lastrowid
        conn.execute("INSERT INTO note_fts(rowid, title, content, topic) VALUES (?, ?, ?, ?)",
                     (row_id, title, content, topic))
        conn.commit()
        conn.close()
        return row_id

    def get_notes(self, limit: int = 10) -> list[dict]:
        conn = self._conn()
        rows = conn.execute("SELECT * FROM notes ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── Usage log ─────────────────────────────────────────────────────────────

    def log_usage(self, model: str, tier: int, input_tokens: int, output_tokens: int,
                  cost_aud: float, task_type: str = "", duration_ms: int = 0):
        now = datetime.now()
        conn = self._conn()
        conn.execute(
            "INSERT INTO usage_log (ts, date, model, tier, input_tokens, output_tokens, "
            "cost_aud, task_type, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now.isoformat(), now.strftime("%Y-%m-%d"), model, tier,
             input_tokens, output_tokens, cost_aud, task_type, duration_ms)
        )
        conn.commit()
        conn.close()

    def get_usage_stats(self) -> dict:
        conn = self._conn()
        today = datetime.now().strftime("%Y-%m-%d")

        def _sum(period_sql, params):
            row = conn.execute(
                f"SELECT SUM(cost_aud) as total, SUM(input_tokens) as inp, "
                f"SUM(output_tokens) as out FROM usage_log WHERE {period_sql}", params
            ).fetchone()
            return {
                "cost_aud": round(row["total"] or 0, 4),
                "input_tokens": row["inp"] or 0,
                "output_tokens": row["out"] or 0,
            }

        stats = {
            "today": _sum("date = ?", (today,)),
            "week": _sum("date >= date('now', '-7 days')", ()),
            "month": _sum("date >= date('now', '-30 days')", ()),
            "all_time": _sum("1=1", ()),
        }

        # Per-model breakdown today
        rows = conn.execute(
            "SELECT model, tier, SUM(cost_aud) as cost FROM usage_log "
            "WHERE date = ? GROUP BY model", (today,)
        ).fetchall()
        stats["by_model_today"] = {r["model"]: round(r["cost"], 4) for r in rows}
        conn.close()
        return stats

    def check_daily_spend_alert(self) -> Optional[float]:
        limit = float(os.getenv("DAILY_SPEND_ALERT_AUD", "2.00"))
        stats = self.get_usage_stats()
        today_spend = stats["today"]["cost_aud"]
        if today_spend >= limit:
            return today_spend
        return None

    # ── Style profile ─────────────────────────────────────────────────────────

    def update_style(self, category: str, key: str, value: str, confidence: float = 0.7):
        conn = self._conn()
        conn.execute(
            "INSERT INTO style_profile (category, key, value, confidence, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(category, key) DO UPDATE SET "
            "value=excluded.value, confidence=excluded.confidence, updated_at=excluded.updated_at",
            (category, key, value, confidence, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

    # ── Session memory extraction ─────────────────────────────────────────────

    def extract_and_store(self, conversation: list[dict]):
        """Store significant user messages as memories after session ends."""
        for msg in conversation:
            if msg["role"] == "user" and len(str(msg.get("content", ""))) > 20:
                self.add_memory(str(msg["content"]), source="user_said")

    async def async_extract_facts(self, user_message: str):
        """Async background fact extraction via Haiku."""
        if len(user_message) < 15:
            return
        try:
            from llm import chat
            result = chat(
                [{"role": "user", "content":
                  f"Extract concrete facts from this message worth remembering long-term. "
                  f"Reply with a JSON array of strings, each a fact. Empty array if nothing noteworthy.\n\n"
                  f"Message: {user_message}"}],
                tier=1
            )
            content = result.get("content", "[]")
            # Parse JSON from response
            import re
            m = re.search(r'\[.*?\]', content, re.DOTALL)
            if m:
                facts = json.loads(m.group())
                for fact in facts[:3]:  # max 3 facts per message
                    if isinstance(fact, str) and len(fact) > 5:
                        self.add_memory(fact, source="extracted", mem_type="fact", importance=6)
        except Exception:
            pass
