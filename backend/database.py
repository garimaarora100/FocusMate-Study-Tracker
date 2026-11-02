"""
Oracle connectivity for FocusMate (python-oracledb, "thin" mode: no Oracle Client needed).

 * Credentials come from .env (never hard-coded).
 * A small connection POOL is created lazily on first use.
 * transaction() gives one connection with automatic COMMIT / ROLLBACK.
 * fetch_all() runs a SELECT with bind variables and returns a list of dicts.

CLI helpers (run from the project root):
    python -m backend.database check      # test the connection
    python -m backend.database setup      # create tables, functions, procedures, views
    python -m backend.database sample     # optional demo data
"""
import argparse
import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import oracledb
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
SQL_DIR = BASE_DIR / "database"
load_dotenv(BASE_DIR / ".env")

_pool = None
_pool_lock = threading.Lock()


class DatabaseConfigError(Exception):
    """Raised when .env does not contain database credentials."""


def _read_config() -> dict:
    user = os.getenv("ORACLE_USER", "").strip()
    password = os.getenv("ORACLE_PASSWORD", "")
    dsn = os.getenv("ORACLE_DSN", "localhost:1521/FREEPDB1").strip()
    if not user or not password:
        raise DatabaseConfigError(
            "ORACLE_USER / ORACLE_PASSWORD are not set. Fill them in the .env file."
        )
    return {"user": user, "password": password, "dsn": dsn}


def get_pool() -> "oracledb.ConnectionPool":
    """Create the pool once (thread-safe) and reuse it."""
    global _pool
    with _pool_lock:
        if _pool is None:
            cfg = _read_config()
            _pool = oracledb.create_pool(min=1, max=5, increment=1, **cfg)
        return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def get_connection():
    """Borrow a connection from the pool and always give it back."""
    conn = get_pool().acquire()
    try:
        yield conn
    finally:
        conn.close()  # for a pooled connection this releases it back to the pool


@contextmanager
def transaction():
    """One unit of work: COMMIT if the block succeeds, ROLLBACK on any exception."""
    with get_connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def fetch_all(sql: str, params: dict | None = None) -> list[dict]:
    """Run a SELECT using bind variables; rows come back as dicts with lower-case keys."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            columns = [col[0].lower() for col in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def check_connection() -> bool:
    """True if a trivial query succeeds."""
    rows = fetch_all("SELECT 1 AS ok FROM dual")
    return bool(rows) and rows[0]["ok"] == 1


# ---------------------------------------------------------------------------
# Script runner (used only by the CLI below)
# ---------------------------------------------------------------------------
def _split_script(text: str) -> list[str]:
    """Split a SQL script into statements. A line holding only '/' ends a statement."""
    statements, buffer = [], []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "/":
            statement = "\n".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
        elif stripped.upper().startswith(("SET ", "PROMPT ")):
            continue  # SQL*Plus-only commands
        else:
            buffer.append(line)
    tail = "\n".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def run_sql_script(filename: str) -> None:
    path = SQL_DIR / filename
    statements = _split_script(path.read_text(encoding="utf-8"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.callproc("DBMS_OUTPUT.ENABLE", [None])
            for statement in statements:
                cur.execute(statement)
            # print anything the script wrote with DBMS_OUTPUT.PUT_LINE
            line_var = cur.var(str)
            status_var = cur.var(int)
            while True:
                cur.callproc("DBMS_OUTPUT.GET_LINE", (line_var, status_var))
                if status_var.getvalue() != 0:
                    break
                print("   ", line_var.getvalue())
        conn.commit()
    print(f"[ok] {filename} ({len(statements)} statement(s))")


def _report_compile_errors() -> int:
    """PL/SQL objects with compile errors are created INVALID without raising - check."""
    errors = fetch_all(
        "SELECT name, type, line, position, text FROM user_errors ORDER BY name, sequence"
    )
    for e in errors:
        print(f"[compile error] {e['type']} {e['name']} line {e['line']}: {e['text']}")
    return len(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description="FocusMate database helper")
    parser.add_argument("command", choices=["check", "setup", "sample"])
    args = parser.parse_args()
    try:
        if args.command == "check":
            print("Connected to Oracle." if check_connection() else "Query failed.")
            return 0
        if args.command == "setup":
            for script in ("create_tables.sql", "functions.sql", "procedures.sql", "views.sql"):
                run_sql_script(script)
            bad = _report_compile_errors()
            print("Setup finished with errors." if bad else "Setup finished successfully.")
            return 1 if bad else 0
        run_sql_script("sample_data.sql")
        return 0
    except (oracledb.Error, DatabaseConfigError) as exc:
        print(f"[failed] {exc}", file=sys.stderr)
        return 1
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(main())
