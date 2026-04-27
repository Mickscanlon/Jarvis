"""
budget.py - Personal + business budgeting engine (Street Appeal Homes context)
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES = [
    ("Fuel", "expense"), ("Equipment", "expense"), ("Labour", "expense"),
    ("Marketing", "expense"), ("Software", "expense"), ("Insurance", "expense"),
    ("Miscellaneous", "expense"), ("Job Revenue", "income"), ("Other Income", "income"),
]


def _init_categories(memory):
    """Seed default budget categories if none exist."""
    try:
        import sqlite3
        from memory import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        existing = conn.execute("SELECT COUNT(*) FROM budget_categories").fetchone()[0]
        if existing == 0:
            for name, cat_type in DEFAULT_CATEGORIES:
                conn.execute(
                    "INSERT OR IGNORE INTO budget_categories (name, category_type) VALUES (?, ?)",
                    (name, cat_type)
                )
            conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[Budget] Init error: {e}")


def log_transaction(memory, category: str, amount: float, direction: str, description: str = "") -> str:
    """Log a transaction (income or expense)."""
    _init_categories(memory)
    try:
        import sqlite3
        from memory import DB_PATH
        now = datetime.now()
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO transactions (category, amount, direction, description, date, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (category, abs(amount), direction, description, now.strftime("%Y-%m-%d"), now.isoformat())
        )
        conn.commit()
        conn.close()
        emoji = "📈" if direction == "income" else "📉"
        return f"Logged: {direction} ${amount:.2f} in {category}. {emoji}"
    except Exception as e:
        return f"Transaction error: {e}"


def get_budget_summary(memory) -> dict:
    """Get current month budget vs actual."""
    _init_categories(memory)
    try:
        import sqlite3
        from memory import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        month = datetime.now().strftime("%Y-%m")

        rows = conn.execute("""
            SELECT t.category, t.direction, SUM(t.amount) as total,
                   bc.monthly_target
            FROM transactions t
            LEFT JOIN budget_categories bc ON t.category = bc.name
            WHERE t.date LIKE ?
            GROUP BY t.category, t.direction
        """, (f"{month}%",)).fetchall()

        total_income = sum(r[2] for r in rows if r[1] == "income")
        total_expense = sum(r[2] for r in rows if r[1] == "expense")

        categories = {}
        for row in rows:
            cat, direction, total, target = row
            if cat not in categories:
                categories[cat] = {"income": 0, "expense": 0, "target": target or 0}
            categories[cat][direction] += total

        conn.close()
        return {
            "month": month,
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "net": round(total_income - total_expense, 2),
            "gst_collected": round(total_income * 0.10, 2),  # 10% GST
            "categories": categories,
        }
    except Exception as e:
        return {"error": str(e)}


def get_business_pl(memory, period: str = "month") -> str:
    """Generate a P&L summary for Street Appeal Homes."""
    summary = get_budget_summary(memory)
    if "error" in summary:
        return f"Budget error: {summary['error']}"

    income = summary["total_income"]
    expense = summary["total_expense"]
    net = summary["net"]
    gst = summary["gst_collected"]

    return (
        f"Street Appeal Homes P&L for {summary['month']}:\n"
        f"Revenue: ${income:.2f}\n"
        f"Expenses: ${expense:.2f}\n"
        f"Net profit: ${net:.2f}\n"
        f"GST collected (10%): ${gst:.2f}\n"
        f"Profit margin: {(net/income*100):.1f}%" if income > 0 else "Net: ${net:.2f}"
    )


def voice_budget_summary(memory) -> str:
    """Compact voice-friendly budget summary."""
    summary = get_budget_summary(memory)
    if "error" in summary:
        return "Budget data not available, sir."
    net = summary["net"]
    direction = "positive" if net >= 0 else "negative"
    return (
        f"This month you've earned ${summary['total_income']:.0f} "
        f"and spent ${summary['total_expense']:.0f}. "
        f"Net is {direction} ${abs(net):.0f}, sir."
    )
