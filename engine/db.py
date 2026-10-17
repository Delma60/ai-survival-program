"""SQLite setup and connection helpers for the World Engine."""

from contextlib import contextmanager
from itertools import count
from pathlib import Path
import sqlite3
from typing import Iterator, Union

PathLike = Union[str, Path]
DB_PATH = Path(__file__).resolve().parent.parent / "world.db"
_SAVEPOINT_IDS = count()

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES agents(id),
    generation INTEGER NOT NULL,
    genome_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'alive' CHECK (status IN ('alive', 'dead')),
    born_day INTEGER NOT NULL DEFAULT 1,
    died_day INTEGER,
    wallet_id INTEGER UNIQUE REFERENCES wallets(id),
    last_action_day INTEGER
);
CREATE TABLE IF NOT EXISTS wallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_agent_id INTEGER NOT NULL UNIQUE REFERENCES agents(id),
    balance INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'internal' CHECK (kind IN ('internal', 'testnet', 'real'))
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    from_wallet INTEGER REFERENCES wallets(id),
    to_wallet INTEGER REFERENCES wallets(id),
    amount INTEGER NOT NULL CHECK (amount > 0),
    reason TEXT NOT NULL,
    ref_id TEXT,
    CHECK (from_wallet IS NOT NULL OR to_wallet IS NOT NULL),
    CHECK (from_wallet IS NULL OR to_wallet IS NULL OR from_wallet != to_wallet)
);
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_agent_id INTEGER NOT NULL REFERENCES agents(id),
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    price INTEGER NOT NULL CHECK (price >= 0),
    stock INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft'
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    buyer_type TEXT NOT NULL,
    buyer_id TEXT NOT NULL,
    price INTEGER NOT NULL CHECK (price >= 0),
    status TEXT NOT NULL DEFAULT 'pending',
    escrow_tx INTEGER REFERENCES transactions(id)
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation INTEGER NOT NULL,
    day INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    source TEXT NOT NULL,
    description TEXT NOT NULL,
    reward INTEGER NOT NULL CHECK (reward > 0),
    verifier TEXT NOT NULL,
    deadline INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'assigned', 'completed', 'failed')),
    assigned_agent_id INTEGER REFERENCES agents(id),
    UNIQUE (generation, day, sequence)
);
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_agent_id INTEGER NOT NULL REFERENCES agents(id),
    kind TEXT NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft'
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    agent_id INTEGER REFERENCES agents(id),
    tool TEXT NOT NULL,
    args_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    agent_id INTEGER REFERENCES agents(id),
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected'))
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    day INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agents_generation ON agents(generation);
CREATE INDEX IF NOT EXISTS idx_events_id ON events(id DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_generation_day ON jobs(generation, day);
"""


def connect(db_path: PathLike = DB_PATH) -> sqlite3.Connection:
    """Open a configured SQLite connection."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def initialize_database(db_path: PathLike = DB_PATH) -> None:
    """Create the schema, enable WAL, and seed dashboard metadata."""
    connection = connect(db_path)
    try:
        with connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
            connection.executemany(
                "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
                [
                    ("paused", "0"),
                    ("generation", "1"),
                    ("day", "1"),
                    ("run_status", "idle"),
                    ("run_seed", "0"),
                ],
            )
    finally:
        connection.close()


@contextmanager
def atomic(connection: sqlite3.Connection) -> Iterator[None]:
    """Run a write atomically, supporting nested engine operations."""
    if connection.in_transaction:
        savepoint = "engine_sp_{}".format(next(_SAVEPOINT_IDS))
        connection.execute("SAVEPOINT {}".format(savepoint))
        try:
            yield
        except Exception:
            connection.execute("ROLLBACK TO SAVEPOINT {}".format(savepoint))
            connection.execute("RELEASE SAVEPOINT {}".format(savepoint))
            raise
        else:
            connection.execute("RELEASE SAVEPOINT {}".format(savepoint))
        return

    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
