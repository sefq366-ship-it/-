# ============================================================
# gif_db.py — CRUD для таблицы gif_cache и настроек
# ============================================================
import aiosqlite
import json

DB_PATH = "sales.db"

async def gif_get(slug: str):
    conn = await aiosqlite.connect(DB_PATH, timeout=30)
    conn.row_factory = aiosqlite.Row
    try:
        cur = await conn.execute("SELECT * FROM gif_cache WHERE slug=?", (slug,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await conn.close()


async def gif_get_ready(slug: str):
    row = await gif_get(slug)
    if row and row.get("status") == "ready" and row.get("mpeg4_file_id"):
        return row
    return None


async def gif_set_pending(slug: str, nft_link: str, gift_name: str,
                          created_by: int, params_json: str = ""):
    conn = await aiosqlite.connect(DB_PATH, timeout=30)
    try:
        await conn.execute(
            """INSERT INTO gif_cache (slug, nft_link, gift_name, status, created_by, params_json)
               VALUES (?,?,?,'pending',?,?)
               ON CONFLICT(slug) DO UPDATE SET
                 nft_link=excluded.nft_link,
                 gift_name=excluded.gift_name,
                 status='pending',
                 error=NULL,
                 params_json=excluded.params_json,
                 created_by=excluded.created_by,
                 updated_at=CURRENT_TIMESTAMP""",
            (slug, nft_link, gift_name, created_by, params_json)
        )
        await conn.commit()
    finally:
        await conn.close()


async def gif_set_ready(slug: str, mpeg4_file_id: str, nft_data: dict,
                        caption: str = "", params_json: str = ""):
    conn = await aiosqlite.connect(DB_PATH, timeout=30)
    try:
        await conn.execute(
            """UPDATE gif_cache SET
                 mpeg4_file_id=?,
                 gift_name=?,
                 model=?,
                 backdrop=?,
                 symbol=?,
                 model_rarity=?,
                 backdrop_rarity=?,
                 symbol_rarity=?,
                 caption=?,
                 params_json=?,
                 status='ready',
                 error=NULL,
                 updated_at=CURRENT_TIMESTAMP
               WHERE slug=?""",
            (
                mpeg4_file_id,
                nft_data.get("gift_name"),
                nft_data.get("model"),
                nft_data.get("backdrop"),
                nft_data.get("symbol"),
                nft_data.get("model_rarity"),
                nft_data.get("backdrop_rarity"),
                nft_data.get("symbol_rarity"),
                caption or "",
                params_json or "",
                slug,
            )
        )
        await conn.commit()
    finally:
        await conn.close()


async def gif_set_error(slug: str, error: str):
    conn = await aiosqlite.connect(DB_PATH, timeout=30)
    try:
        await conn.execute(
            "UPDATE gif_cache SET status='error', error=?, updated_at=CURRENT_TIMESTAMP WHERE slug=?",
            (error[:1000], slug)
        )
        await conn.commit()
    finally:
        await conn.close()


async def gif_update_meta(slug: str, meta: dict):
    allowed = {
        "gift_name", "model", "backdrop", "symbol",
        "model_rarity", "backdrop_rarity", "symbol_rarity", "caption",
    }
    fields = [k for k in meta.keys() if k in allowed]
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    values = [meta[k] for k in fields]
    values.append(slug)
    conn = await aiosqlite.connect(DB_PATH, timeout=30)
    try:
        await conn.execute(
            f"UPDATE gif_cache SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE slug=?",
            values
        )
        await conn.commit()
    finally:
        await conn.close()


async def gif_list(status: str = None, limit: int = 50):
    conn = await aiosqlite.connect(DB_PATH, timeout=30)
    conn.row_factory = aiosqlite.Row
    try:
        if status:
            cur = await conn.execute(
                "SELECT * FROM gif_cache WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                (status, limit)
            )
        else:
            cur = await conn.execute(
                "SELECT * FROM gif_cache ORDER BY updated_at DESC LIMIT ?",
                (limit,)
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def gif_search(query: str, limit: int = 20):
    conn = await aiosqlite.connect(DB_PATH, timeout=30)
    conn.row_factory = aiosqlite.Row
    try:
        q = f"%{query.strip()}%"
        cur = await conn.execute(
            """SELECT * FROM gif_cache
               WHERE status='ready' AND mpeg4_file_id IS NOT NULL
                 AND (slug LIKE ? OR gift_name LIKE ? OR model LIKE ? OR backdrop LIKE ? OR symbol LIKE ?)
               ORDER BY updated_at DESC LIMIT ?""",
            (q, q, q, q, q, limit)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def gif_delete(slug: str):
    conn = await aiosqlite.connect(DB_PATH, timeout=30)
    try:
        await conn.execute("DELETE FROM gif_cache WHERE slug=?", (slug,))
        await conn.commit()
    finally:
        await conn.close()


async def gif_count_by_status():
    conn = await aiosqlite.connect(DB_PATH, timeout=30)
    try:
        cur = await conn.execute("SELECT status, COUNT(*) FROM gif_cache GROUP BY status")
        rows = await cur.fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        await conn.close()

# ===== НОВОЕ: Настройки бота =====

async def get_bot_settings():
    """Возвращает глобальные настройки рендера"""
    default_settings = {
        "card_w": 800,
        "card_h": 450,
        "fps": 24,
        "frame_skip": 2,
        "crf": 23,
        "preset": "veryfast",
        "sticker_file_id": ""  # file_id заглушки
    }
    conn = await aiosqlite.connect(DB_PATH, timeout=30)
    try:
        cur = await conn.execute("SELECT key, value FROM bot_settings")
        rows = await cur.fetchall()
        for k, v in rows:
            if k in default_settings:
                if k in ["card_w", "card_h", "fps", "frame_skip", "crf"]:
                    default_settings[k] = int(v)
                else:
                    default_settings[k] = v
        return default_settings
    finally:
        await conn.close()


async def save_bot_setting(key: str, value: str):
    conn = await aiosqlite.connect(DB_PATH, timeout=30)
    try:
        await conn.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?,?)", (key, str(value)))
        await conn.commit()
    finally:
        await conn.close()
