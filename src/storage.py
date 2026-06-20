from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import DB_PATH


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS live_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                event_payload TEXT NOT NULL,
                prediction_payload TEXT NOT NULL,
                impact_score REAL NOT NULL,
                risk_level TEXT NOT NULL,
                approval_status TEXT NOT NULL DEFAULT 'pending',
                reviewer TEXT,
                approval_note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                live_event_id INTEGER,
                actor TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source": row["source"],
        "event": json.loads(row["event_payload"]),
        "prediction": json.loads(row["prediction_payload"]),
        "impact_score": row["impact_score"],
        "risk_level": row["risk_level"],
        "approval_status": row["approval_status"],
        "reviewer": row["reviewer"],
        "approval_note": row["approval_note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_live_event(event_payload: dict, prediction_payload: dict, source: str = "manual") -> dict[str, Any]:
    init_db()
    now = utc_now()
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO live_events (
                source, event_payload, prediction_payload, impact_score, risk_level,
                approval_status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                source,
                json.dumps(event_payload, default=str),
                json.dumps(prediction_payload, default=str),
                prediction_payload["impact_score"],
                prediction_payload["risk_level"],
                now,
                now,
            ),
        )
        live_event_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO audit_log (action, live_event_id, actor, details, created_at)
            VALUES ('live_event_created', ?, 'system', ?, ?)
            """,
            (live_event_id, json.dumps({"source": source, "risk_level": prediction_payload["risk_level"]}), now),
        )
        row = conn.execute("SELECT * FROM live_events WHERE id = ?", (live_event_id,)).fetchone()
        return _decode_row(row)


def list_live_events(limit: int = 20) -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM live_events ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        ).fetchall()
        return [_decode_row(row) for row in rows]


def update_approval(live_event_id: int, status: str, reviewer: str, note: str = "") -> dict[str, Any] | None:
    init_db()
    now = utc_now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM live_events WHERE id = ?", (live_event_id,)).fetchone()
        if row is None:
            return None
        conn.execute(
            """
            UPDATE live_events
            SET approval_status = ?, reviewer = ?, approval_note = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, reviewer, note, now, live_event_id),
        )
        conn.execute(
            """
            INSERT INTO audit_log (action, live_event_id, actor, details, created_at)
            VALUES ('approval_updated', ?, ?, ?, ?)
            """,
            (live_event_id, reviewer, json.dumps({"status": status, "note": note}), now),
        )
        updated = conn.execute("SELECT * FROM live_events WHERE id = ?", (live_event_id,)).fetchone()
        return _decode_row(updated)


def audit_log(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [dict(row) for row in rows]


def operational_summary() -> dict[str, Any]:
    init_db()
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM live_events").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM live_events WHERE approval_status = 'pending'").fetchone()[0]
        approved = conn.execute("SELECT COUNT(*) FROM live_events WHERE approval_status = 'approved'").fetchone()[0]
        rejected = conn.execute("SELECT COUNT(*) FROM live_events WHERE approval_status = 'rejected'").fetchone()[0]
        avg_score = conn.execute("SELECT AVG(impact_score) FROM live_events").fetchone()[0]
        critical = conn.execute("SELECT COUNT(*) FROM live_events WHERE risk_level = 'Critical'").fetchone()[0]
        high = conn.execute("SELECT COUNT(*) FROM live_events WHERE risk_level = 'High'").fetchone()[0]
    return {
        "db_path": str(DB_PATH),
        "live_events_total": total,
        "pending_approvals": pending,
        "approved": approved,
        "rejected": rejected,
        "high_or_critical_events": high + critical,
        "average_impact_score": round(float(avg_score or 0), 2),
    }
