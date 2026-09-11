"""Lapisan penyimpanan SQLite.

Tabel:
- employees(id, name, created_at)
- embeddings(id, employee_id, vector BLOB, source, created_at)
- attendance(id, work_date, employee_id, clock_in, clock_out, in_count, out_count, updated_at)

Embedding disimpan sebagai float32 numpy bytes agar hemat & cepat dimuat.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS embeddings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    vector      BLOB NOT NULL,
    source      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS attendance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    work_date   TEXT NOT NULL,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    clock_in    TEXT,
    clock_out   TEXT,
    in_count    INTEGER NOT NULL DEFAULT 0,
    out_count   INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(work_date, employee_id)
);

CREATE INDEX IF NOT EXISTS idx_emb_emp ON embeddings(employee_id);
CREATE INDEX IF NOT EXISTS idx_att_date ON attendance(work_date);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str | Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def session(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------- employees & embeddings ----------

def upsert_employee(conn: sqlite3.Connection, name: str) -> int:
    conn.execute("INSERT OR IGNORE INTO employees(name) VALUES (?)", (name,))
    row = conn.execute("SELECT id FROM employees WHERE name = ?", (name,)).fetchone()
    return int(row["id"])


def add_embedding(conn: sqlite3.Connection, employee_id: int, vector: np.ndarray, source: str) -> None:
    blob = np.asarray(vector, dtype=np.float32).tobytes()
    conn.execute(
        "INSERT INTO embeddings(employee_id, vector, source) VALUES (?, ?, ?)",
        (employee_id, blob, source),
    )


def clear_embeddings_for(conn: sqlite3.Connection, employee_id: int) -> None:
    conn.execute("DELETE FROM embeddings WHERE employee_id = ?", (employee_id,))


def load_gallery(conn: sqlite3.Connection) -> tuple[np.ndarray, list[str], list[int]]:
    """Muat semua embedding + nama karyawan untuk pencocokan.

    Returns (matrix [N x D] float32, names[N], employee_ids[N]).
    Vektor dinormalisasi L2 agar dot-product == cosine similarity.
    """
    rows = conn.execute(
        """
        SELECT e.vector AS vector, emp.name AS name, emp.id AS emp_id
        FROM embeddings e JOIN employees emp ON emp.id = e.employee_id
        ORDER BY emp.id
        """
    ).fetchall()
    if not rows:
        return np.zeros((0, 512), dtype=np.float32), [], []

    vectors = np.stack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
    # normalisasi L2 (jaga-jaga bila belum ternormalisasi saat disimpan)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors = vectors / norms
    names = [r["name"] for r in rows]
    emp_ids = [int(r["emp_id"]) for r in rows]
    return vectors.astype(np.float32), names, emp_ids


def list_employees(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT emp.id, emp.name, COUNT(e.id) AS n_emb
        FROM employees emp LEFT JOIN embeddings e ON e.employee_id = emp.id
        GROUP BY emp.id ORDER BY emp.name
        """
    ).fetchall()


# ---------- attendance ----------

def record_clock_in(conn: sqlite3.Connection, work_date: str, employee_id: int, ts: str) -> None:
    """Set clock_in ke deteksi PERTAMA (tidak menimpa bila sudah ada); naikkan in_count."""
    conn.execute(
        """
        INSERT INTO attendance(work_date, employee_id, clock_in, in_count, updated_at)
        VALUES (?, ?, ?, 1, datetime('now','localtime'))
        ON CONFLICT(work_date, employee_id) DO UPDATE SET
            clock_in = COALESCE(attendance.clock_in, excluded.clock_in),
            in_count = attendance.in_count + 1,
            updated_at = datetime('now','localtime')
        """,
        (work_date, employee_id, ts),
    )


def record_clock_out(conn: sqlite3.Connection, work_date: str, employee_id: int, ts: str) -> None:
    """Set clock_out ke deteksi TERAKHIR (selalu timpa dengan ts terbaru); naikkan out_count."""
    conn.execute(
        """
        INSERT INTO attendance(work_date, employee_id, clock_out, out_count, updated_at)
        VALUES (?, ?, ?, 1, datetime('now','localtime'))
        ON CONFLICT(work_date, employee_id) DO UPDATE SET
            clock_out = excluded.clock_out,
            out_count = attendance.out_count + 1,
            updated_at = datetime('now','localtime')
        """,
        (work_date, employee_id, ts),
    )


def get_day_attendance(conn: sqlite3.Connection, work_date: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT emp.name AS name, a.clock_in, a.clock_out, a.in_count, a.out_count
        FROM attendance a JOIN employees emp ON emp.id = a.employee_id
        WHERE a.work_date = ?
        ORDER BY emp.name
        """,
        (work_date,),
    ).fetchall()
