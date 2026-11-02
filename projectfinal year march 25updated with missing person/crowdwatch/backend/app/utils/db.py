import sqlite3
from pathlib import Path
from ..config import DB_PATH

def init_db():
    p = Path(DB_PATH)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      camera TEXT,
      type TEXT,
      payload TEXT,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS cameras (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      camera_id TEXT,
      uri TEXT,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    return conn

_conn = init_db()

def save_alert(camera, typ, payload):
    cur = _conn.cursor()
    cur.execute("INSERT INTO alerts (camera, type, payload) VALUES (?, ?, ?)", (camera, typ, str(payload)))
    _conn.commit()
