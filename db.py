import sqlite3
import shutil
import os
from datetime import datetime
from contextlib import closing

DB_PATH = "bot.db"

def init_db():
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            points INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            best_streak INTEGER DEFAULT 0,
            theme TEXT DEFAULT 'light',
            lang TEXT DEFAULT 'ru',
            referred_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            otchestvo TEXT,
            father TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS favorites(
            user_id INTEGER,
            otchestvo TEXT,
            PRIMARY KEY(user_id, otchestvo)
        );
        CREATE TABLE IF NOT EXISTS achievements(
            user_id INTEGER,
            code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, code)
        );
        CREATE TABLE IF NOT EXISTS stats(
            key TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0
        );
        """)
        con.commit()
    migrate_db()

def migrate_db():
    """Безопасно добавляет недостающие колонки и таблицы. Данные не трогает."""
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()

        cur.execute("PRAGMA table_info(users)")
        existing = {row[1] for row in cur.fetchall()}

        wanted = [
            ("referrals",     "INTEGER DEFAULT 0"),
            ("premium",       "INTEGER DEFAULT 0"),
            ("last_daily",    "TEXT"),
            ("daily_streak",  "INTEGER DEFAULT 0"),
            ("daily_done",    "TEXT"),
            ("answer_style",  "TEXT DEFAULT 'normal'"),
        ]
        for name, ddl in wanted:
            if name not in existing:
                try:
                    cur.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
                except sqlite3.OperationalError:
                    pass

        cur.executescript("""
        CREATE TABLE IF NOT EXISTS quests(
            user_id INTEGER,
            code TEXT,
            progress INTEGER DEFAULT 0,
            done INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, code)
        );
        CREATE TABLE IF NOT EXISTS duels(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger INTEGER,
            opponent INTEGER,
            c_score INTEGER DEFAULT 0,
            o_score INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        con.commit()

def backup_db():
    if os.path.exists(DB_PATH):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            os.makedirs("backups", exist_ok=True)
            shutil.copy(DB_PATH, f"backups/bot_{ts}.db")
        except Exception:
            pass

def get_user(user_id):
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        return cur.fetchone()

def create_user(user_id, username, first_name, referred_by=None):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO users(user_id, username, first_name, referred_by) VALUES(?,?,?,?)",
            (user_id, username, first_name, referred_by),
        )
        con.commit()

def update_user_profile(user_id, username, first_name):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?",
                    (username, first_name, user_id))
        con.commit()

def set_referred_by(user_id, referrer_id):
    if user_id == referrer_id:
        return False
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("SELECT referred_by FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row is None:
            cur.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
            current = None
        else:
            current = row[0]
        if current:
            return False
        cur.execute("UPDATE users SET referred_by=? WHERE user_id=?", (referrer_id, user_id))
        con.commit()
        return True

def add_points(user_id, pts):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("INSERT OR IGNORE INTO users(user_id, points) VALUES(?, 0)", (user_id,))
        cur.execute("UPDATE users SET points=points+? WHERE user_id=?", (pts, user_id))
        con.commit()

def add_referral(user_id):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("INSERT OR IGNORE INTO users(user_id, referrals) VALUES(?, 0)", (user_id,))
        cur.execute("UPDATE users SET referrals=referrals+1 WHERE user_id=?", (user_id,))
        con.commit()

def inc_streak(user_id, correct=True):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("INSERT OR IGNORE INTO users(user_id, streak, best_streak) VALUES(?,0,0)", (user_id,))
        if correct:
            cur.execute("UPDATE users SET streak=streak+1 WHERE user_id=?", (user_id,))
            cur.execute("UPDATE users SET best_streak=MAX(best_streak, streak) WHERE user_id=?", (user_id,))
        else:
            cur.execute("UPDATE users SET streak=0 WHERE user_id=?", (user_id,))
        con.commit()

def add_history(user_id, otch, father):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("INSERT INTO history(user_id, otchestvo, father) VALUES(?,?,?)", (user_id, otch, father))
        cur.execute("INSERT INTO stats(key,value) VALUES('total_queries',1) ON CONFLICT(key) DO UPDATE SET value=value+1")
        con.commit()

def get_history(user_id, limit=10):
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT * FROM history WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
        return cur.fetchall()

def get_last_father(user_id):
    """Имя отца из последнего запроса пользователя (для паспорта)."""
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("SELECT father FROM history WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None

def add_favorite(user_id, otch):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("INSERT OR IGNORE INTO favorites(user_id, otchestvo) VALUES(?,?)", (user_id, otch))
        con.commit()

def remove_favorite(user_id, otch):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("DELETE FROM favorites WHERE user_id=? AND otchestvo=?", (user_id, otch))
        con.commit()

def get_favorites(user_id):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("SELECT otchestvo FROM favorites WHERE user_id=?", (user_id,))
        return [r[0] for r in cur.fetchall()]

def grant_achievement(user_id, code) -> bool:
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        try:
            cur.execute("INSERT INTO achievements(user_id, code) VALUES(?,?)", (user_id, code))
            con.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def get_achievements(user_id):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("SELECT code FROM achievements WHERE user_id=?", (user_id,))
        return [r[0] for r in cur.fetchall()]

def top_users(limit=10):
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT first_name, username, points, best_streak FROM users ORDER BY points DESC LIMIT ?", (limit,))
        return cur.fetchall()

def top_referrers(limit=10):
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT first_name, username, referrals FROM users WHERE referrals>0 ORDER BY referrals DESC LIMIT ?", (limit,))
        return cur.fetchall()

def set_theme(user_id, theme):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("UPDATE users SET theme=? WHERE user_id=?", (theme, user_id))
        con.commit()

def set_answer_style(user_id, style):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("UPDATE users SET answer_style=? WHERE user_id=?", (style, user_id))
        con.commit()

def set_daily(user_id, date_str, daily_streak):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("UPDATE users SET last_daily=?, daily_done=?, daily_streak=? WHERE user_id=?",
                    (date_str, date_str, daily_streak, user_id))
        con.commit()

def set_premium(user_id, value):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("INSERT OR IGNORE INTO users(user_id, premium) VALUES(?, 0)", (user_id,))
        cur.execute("UPDATE users SET premium=? WHERE user_id=?", (value, user_id))
        con.commit()

# ---------- Квесты ----------
def quest_get(user_id, code):
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT * FROM quests WHERE user_id=? AND code=?", (user_id, code))
        return cur.fetchone()

def quest_set(user_id, code, progress, done=0):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO quests(user_id, code, progress, done, updated_at)
            VALUES(?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, code) DO UPDATE SET
                progress=excluded.progress,
                done=excluded.done,
                updated_at=CURRENT_TIMESTAMP
        """, (user_id, code, progress, done))
        con.commit()

def quest_all(user_id):
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT * FROM quests WHERE user_id=?", (user_id,))
        return cur.fetchall()

# ---------- Дуэли ----------
def duel_create(challenger, opponent):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("INSERT INTO duels(challenger, opponent) VALUES(?,?)", (challenger, opponent))
        con.commit()
        return cur.lastrowid

def duel_get(duel_id):
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT * FROM duels WHERE id=?", (duel_id,))
        return cur.fetchone()

def duel_update(duel_id, c_score, o_score, status):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("UPDATE duels SET c_score=?, o_score=?, status=? WHERE id=?",
                    (c_score, o_score, status, duel_id))
        con.commit()

# ---------- Глобальная статистика ----------
def global_stats():
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) AS users FROM users")
        users = cur.fetchone()["users"]
        cur.execute("SELECT value FROM stats WHERE key='total_queries'")
        row = cur.fetchone()
        queries = row["value"] if row else 0
        cur.execute("SELECT otchestvo, COUNT(*) c FROM history GROUP BY otchestvo ORDER BY c DESC LIMIT 5")
        top = cur.fetchall()
        return users, queries, top

def all_user_ids():
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("SELECT user_id FROM users")
        return [r[0] for r in cur.fetchall()]
