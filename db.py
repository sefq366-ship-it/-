import sqlite3
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            daily_date TEXT,
            daily_done INTEGER DEFAULT 0
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

def add_points(user_id, pts):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("UPDATE users SET points=points+? WHERE user_id=?", (pts, user_id))
        con.commit()

def inc_streak(user_id, correct=True):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
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
    """True, если выдали впервые."""
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

def set_theme(user_id, theme):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("UPDATE users SET theme=? WHERE user_id=?", (theme, user_id))
        con.commit()

def set_daily(user_id, date_str, done):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.cursor()
        cur.execute("UPDATE users SET daily_date=?, daily_done=? WHERE user_id=?", (date_str, done, user_id))
        con.commit()

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

def top_otchestva(limit=5):
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT otchestvo, COUNT(*) c FROM history GROUP BY otchestvo ORDER BY c DESC LIMIT ?", (limit,))
        return cur.fetchall()
