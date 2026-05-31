"""SSLAB Admin Platform - Database Models (aiosqlite)"""
import aiosqlite
import time
from config import DB_PATH


async def init_db():
    """Initialize database tables"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS firmware (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name TEXT NOT NULL DEFAULT 'com.lab.management',
                version_code INTEGER NOT NULL,
                version_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                changelog TEXT DEFAULT '',
                upload_time REAL NOT NULL,
                is_active INTEGER DEFAULT 1,
                min_version_code INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS terminal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL UNIQUE,
                device_name TEXT DEFAULT '',
                app_version TEXT DEFAULT '',
                version_code INTEGER DEFAULT 0,
                ip_address TEXT DEFAULT '',
                device_info TEXT DEFAULT '{}',
                current_state TEXT DEFAULT '{}',
                last_heartbeat REAL DEFAULT 0,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS terminal_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                log_level TEXT DEFAULT 'INFO',
                message TEXT NOT NULL,
                timestamp REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS command_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                command_type TEXT NOT NULL,
                command_data TEXT NOT NULL DEFAULT '{}',
                response TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at REAL NOT NULL,
                executed_at REAL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_terminal_device_id ON terminal(device_id);
            CREATE INDEX IF NOT EXISTS idx_terminal_log_device ON terminal_log(device_id);
            CREATE INDEX IF NOT EXISTS idx_terminal_log_ts ON terminal_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_command_device ON command_queue(device_id);
            CREATE INDEX IF NOT EXISTS idx_command_status ON command_queue(status);

            CREATE TABLE IF NOT EXISTS update_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                firmware_id INTEGER NOT NULL,
                from_version_code INTEGER DEFAULT 0,
                to_version_code INTEGER NOT NULL,
                to_version_name TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at REAL NOT NULL,
                updated_at REAL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_update_device ON update_history(device_id);
        """)
        await db.commit()
    # 兼容旧数据库：补加 min_version_code 列
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("ALTER TABLE firmware ADD COLUMN min_version_code INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass  # 列已存在，忽略
    print("[DB] Database initialized")


async def get_db():
    """Get database connection"""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


# ========== Firmware CRUD ==========

async def create_firmware(app_name, version_code, version_name, file_path, file_size, changelog="", min_version_code=0):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO firmware (app_name, version_code, version_name, file_path, file_size, changelog, upload_time, min_version_code) VALUES (?,?,?,?,?,?,?,?)",
            (app_name, version_code, version_name, file_path, file_size, changelog, time.time(), min_version_code)
        )
        await db.commit()
        cursor = await db.execute("SELECT last_insert_rowid()")
        row = await cursor.fetchone()
        return row[0]
    finally:
        await db.close()


async def list_firmware(app_name=None, limit=50):
    db = await get_db()
    try:
        if app_name:
            cursor = await db.execute(
                "SELECT * FROM firmware WHERE app_name=? ORDER BY version_code DESC LIMIT ?",
                (app_name, limit)
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM firmware ORDER BY version_code DESC LIMIT ?", (limit,)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_latest_firmware(app_name="com.lab.management", current_version_code=0):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM firmware WHERE app_name=? AND is_active=1 AND min_version_code<=? ORDER BY version_code DESC LIMIT 1",
            (app_name, current_version_code)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_firmware_by_id(firmware_id):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM firmware WHERE id=?", (firmware_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def delete_firmware(firmware_id):
    db = await get_db()
    try:
        await db.execute("DELETE FROM firmware WHERE id=?", (firmware_id,))
        await db.commit()
    finally:
        await db.close()


async def toggle_firmware(firmware_id, is_active):
    db = await get_db()
    try:
        await db.execute("UPDATE firmware SET is_active=? WHERE id=?", (is_active, firmware_id))
        await db.commit()
    finally:
        await db.close()


# ========== Terminal CRUD ==========

async def upsert_terminal(device_id, device_name="", app_version="", version_code=0,
                          ip_address="", device_info="{}", current_state="{}"):
    now = time.time()
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM terminal WHERE device_id=?", (device_id,))
        existing = await cursor.fetchone()
        if existing:
            await db.execute(
                """UPDATE terminal SET device_name=?, app_version=?, version_code=?,
                   ip_address=?, device_info=?, current_state=?, last_heartbeat=?
                   WHERE device_id=?""",
                (device_name, app_version, version_code, ip_address, device_info, current_state, now, device_id)
            )
        else:
            await db.execute(
                """INSERT INTO terminal (device_id, device_name, app_version, version_code,
                   ip_address, device_info, current_state, last_heartbeat, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (device_id, device_name, app_version, version_code, ip_address, device_info, current_state, now, now)
            )
        await db.commit()
    finally:
        await db.close()


async def list_terminals():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM terminal ORDER BY last_heartbeat DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_terminal(device_id):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM terminal WHERE device_id=?", (device_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


# ========== Terminal Log ==========

async def insert_logs(device_id, logs):
    """Batch insert logs: logs = [{"level":"INFO","message":"...","timestamp":123.4}, ...]"""
    db = await get_db()
    try:
        for log in logs:
            await db.execute(
                "INSERT INTO terminal_log (device_id, log_level, message, timestamp) VALUES (?,?,?,?)",
                (device_id, log.get("level", "INFO"), log.get("message", ""), log.get("timestamp", time.time()))
            )
        await db.commit()
    finally:
        await db.close()


async def get_logs(device_id=None, level=None, limit=200, offset=0):
    db = await get_db()
    try:
        conditions = []
        params = []
        if device_id:
            conditions.append("device_id=?")
            params.append(device_id)
        if level:
            conditions.append("log_level=?")
            params.append(level)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"SELECT * FROM terminal_log{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ========== Command Queue ==========

async def enqueue_command(device_id, command_type, command_data="{}"):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO command_queue (device_id, command_type, command_data, status, created_at) VALUES (?,?,?,?,?)",
            (device_id, command_type, command_data, "pending", time.time())
        )
        await db.commit()
        cursor = await db.execute("SELECT last_insert_rowid()")
        row = await cursor.fetchone()
        return row[0]
    finally:
        await db.close()


async def get_pending_commands(device_id, limit=10):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM command_queue WHERE device_id=? AND status='pending' ORDER BY created_at ASC LIMIT ?",
            (device_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def update_command_result(command_id, response, status="done"):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE command_queue SET response=?, status=?, executed_at=? WHERE id=?",
            (response, status, time.time(), command_id)
        )
        await db.commit()
    finally:
        await db.close()


async def get_command_history(device_id=None, limit=100):
    db = await get_db()
    try:
        if device_id:
            cursor = await db.execute(
                "SELECT * FROM command_queue WHERE device_id=? ORDER BY created_at DESC LIMIT ?",
                (device_id, limit)
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM command_queue ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ========== Update History ==========

async def create_update_record(device_id, firmware_id, from_version_code, to_version_code, to_version_name):
    db = await get_db()
    try:
        now = time.time()
        await db.execute(
            """INSERT INTO update_history (device_id, firmware_id, from_version_code, to_version_code,
               to_version_name, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)""",
            (device_id, firmware_id, from_version_code, to_version_code, to_version_name, "pending", now, now)
        )
        await db.commit()
        cursor = await db.execute("SELECT last_insert_rowid()")
        row = await cursor.fetchone()
        return row[0]
    finally:
        await db.close()


async def update_update_status(device_id, version_code, status):
    db = await get_db()
    try:
        await db.execute(
            """UPDATE update_history SET status=?, updated_at=?
               WHERE device_id=? AND to_version_code=? AND status NOT IN ('installed','failed')""",
            (status, time.time(), device_id, version_code)
        )
        await db.commit()
    finally:
        await db.close()


async def get_update_history(device_id=None, limit=50):
    db = await get_db()
    try:
        if device_id:
            cursor = await db.execute(
                "SELECT * FROM update_history WHERE device_id=? ORDER BY created_at DESC LIMIT ?",
                (device_id, limit)
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM update_history ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()
