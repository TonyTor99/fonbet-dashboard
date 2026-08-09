"""Постоянная история расчётов (SQLite), отдельно по каждому источнику.

Хранит снимок формы (для восстановления UI), параметры бэктеста и краткую сводку.
БД лежит в корне проекта (history.db), не в snapshots.
"""
import os
import json
import sqlite3
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "history.db")

MAX_PER_SOURCE = 50  # сколько записей храним на источник


def _con():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = _con()
    con.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            source     TEXT NOT NULL,
            ts         TEXT NOT NULL,
            form       TEXT NOT NULL,
            params     TEXT NOT NULL,
            summary    TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_history_source ON history(source)")
    con.commit()
    con.close()


def _row_to_entry(r):
    return {
        "id": r["id"], "ts": r["ts"],
        "form": json.loads(r["form"]),
        "params": json.loads(r["params"]),
        "summary": json.loads(r["summary"]),
    }


def add(source, form, params, summary):
    ts = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    now = datetime.datetime.now().isoformat(timespec="seconds")
    con = _con()
    cur = con.execute(
        "INSERT INTO history(source, ts, form, params, summary, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (source, ts,
         json.dumps(form, ensure_ascii=False),
         json.dumps(params, ensure_ascii=False),
         json.dumps(summary, ensure_ascii=False), now))
    rid = cur.lastrowid
    # держим не более MAX_PER_SOURCE последних записей на источник
    con.execute(
        "DELETE FROM history WHERE source=? AND id NOT IN "
        "(SELECT id FROM history WHERE source=? ORDER BY id DESC LIMIT ?)",
        (source, source, MAX_PER_SOURCE))
    con.commit()
    row = con.execute("SELECT * FROM history WHERE id=?", (rid,)).fetchone()
    con.close()
    return _row_to_entry(row)


def list_entries(source):
    con = _con()
    rows = con.execute(
        "SELECT * FROM history WHERE source=? ORDER BY id DESC", (source,)).fetchall()
    con.close()
    return [_row_to_entry(r) for r in rows]


def delete(source, entry_id):
    con = _con()
    con.execute("DELETE FROM history WHERE source=? AND id=?", (source, entry_id))
    con.commit()
    con.close()


def clear(source):
    con = _con()
    con.execute("DELETE FROM history WHERE source=?", (source,))
    con.commit()
    con.close()
