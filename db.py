import json
import os
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
UPLOADS = DATA / "uploads"
RESULTS = DATA / "results"
STATUS = BASE / "public" / "status"
DB_PATH = DATA / "jobs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  step TEXT,
  progress INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  worker TEXT,
  created_at INTEGER NOT NULL,
  started_at INTEGER,
  finished_at INTEGER
);
CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs(status, created_at);
"""


def connect():
    for folder in (UPLOADS, RESULTS, STATUS):
        folder.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(SCHEMA)
    return conn


def write_json(folder, job_id, payload):
    tmp = folder / f"{job_id}.json.tmp"
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, folder / f"{job_id}.json")


def write_status(job_id, payload):
    write_json(STATUS, job_id, payload)
