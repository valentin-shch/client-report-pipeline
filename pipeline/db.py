"""Postgres access. Plain psycopg and plain SQL files; the schema is small
enough that re-running CREATE TABLE IF NOT EXISTS is all the migration it needs.

    python -m pipeline.db init

Run init with the owner's URL. The pipeline and app roles can't change the
schema on purpose, so init is a setup step, never part of a run.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
import psycopg

SQL_DIR = Path(__file__).resolve().parent.parent / "db"
TABLES = ("raw_ads", "raw_deals", "raw_fx", "clean_ads", "clean_deals", "runs")


def connect(url: str | None = None) -> psycopg.Connection:
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(url)


def init_schema(conn: psycopg.Connection) -> None:
    for name in ("schema.sql", "grants.sql"):
        conn.execute((SQL_DIR / name).read_text(encoding="utf-8"))
    conn.commit()


def read_frame(conn: psycopg.Connection, sql: str, params: tuple | dict = ()) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=columns)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init"])
    parser.parse_args()
    with connect() as conn:
        init_schema(conn)
    print("schema ready")
