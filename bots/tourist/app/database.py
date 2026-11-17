"""SQLite database and schema. All write operations use BEGIN IMMEDIATE."""
import sqlite3
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from app.config import settings


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def database_path() -> Path:
    # The storage location must not change when the program is invoked from
    # another working directory (Windows shortcut, Task Scheduler, service).
    path = Path(settings.database_path).expanduser()
    if not path.is_absolute():
        from app.config import ROOT
        path = ROOT / path
    return path.resolve()


def connect() -> sqlite3.Connection:
    p = database_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p), timeout=15, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=15000')
    c.execute('PRAGMA journal_mode=WAL')
    return c


@contextmanager
def session(write=False):
    c = connect()
    try:
        c.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def init_db():
    with session(write=True) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL DEFAULT '',
            full_name TEXT,
            phone TEXT,
            nickname TEXT,
            nickname_key TEXT UNIQUE,
            role TEXT NOT NULL DEFAULT 'guest' CHECK(role IN ('guest','admin','senior','owner')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK(kind IN ('mafia','poker')),
            title TEXT NOT NULL,
            format TEXT,
            starts_at TEXT NOT NULL,
            capacity INTEGER NOT NULL CHECK(capacity BETWEEN 1 AND 100),
            min_players INTEGER NOT NULL DEFAULT 1,
            stack TEXT,
            blinds TEXT,
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed','cancelled')),
            created_by INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL REFERENCES events(id),
            telegram_id INTEGER NOT NULL REFERENCES users(telegram_id),
            nickname_snapshot TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','confirmed','rejected','cancel_requested','cancelled')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(event_id,telegram_id)
        );
        CREATE TABLE IF NOT EXISTS billiard_bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL REFERENCES users(telegram_id),
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            guest_count INTEGER NOT NULL CHECK(guest_count BETWEEN 1 AND 30),
            status TEXT NOT NULL CHECK(status IN ('pending','confirmed','rejected','cancel_requested','cancelled')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_billiard_time ON billiard_bookings(starts_at, ends_at, status);
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notification_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_key TEXT NOT NULL,
            telegram_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','sent','failed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL,
            sent_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_outbox_due ON notification_outbox(state,next_attempt_at);
        -- Deduplicate retrying requests atomically with the booking transaction.
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            telegram_id INTEGER NOT NULL,
            operation TEXT NOT NULL,
            request_key TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            result_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (telegram_id,operation,request_key)
        );
        CREATE INDEX IF NOT EXISTS ix_idempotency_created ON idempotency_keys(created_at);
                CREATE TABLE IF NOT EXISTS bot_identity (
            id INTEGER PRIMARY KEY CHECK(id=1),
            token_fingerprint TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sync_jobs (
            id INTEGER PRIMARY KEY CHECK(id=1),
            revision INTEGER NOT NULL DEFAULT 0,
            synced_revision INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            updated_at TEXT NOT NULL
        );
        INSERT OR IGNORE INTO sync_jobs (id,updated_at) VALUES (1,datetime('now'));
        ''')
    # SQLite executescript commits its own implicit transaction. Keep schema upgrades
    # in a separate IMMEDIATE transaction and make every ALTER idempotent, so an
    # existing v0.2 database remains readable and its records remain intact.
    with session(write=True) as c:
        for table, additions in {
            'applications': {'cancel_origin': 'TEXT'},
            'billiard_bookings': {'cancel_origin': 'TEXT'},
            'sync_jobs': {'synced_once': 'INTEGER NOT NULL DEFAULT 0'},
            'notification_outbox': {
                'purpose': "TEXT NOT NULL DEFAULT 'system'",
                'entity_type': 'TEXT',
                'entity_id': 'INTEGER',
            },
        }.items():
            existing = {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
            for column, declaration in additions.items():
                if column not in existing:
                    c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {declaration}')
        c.execute("CREATE INDEX IF NOT EXISTS ix_outbox_reminders ON notification_outbox(purpose,entity_type,entity_id,state)")
        # Showcase events remain distinguishable from real client events.
        columns = {r['name'] for r in c.execute('PRAGMA table_info(events)')}
        if 'is_demo' not in columns:
            c.execute('ALTER TABLE events ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0')
        c.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL REFERENCES users(telegram_id),
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','answered','closed')),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL REFERENCES support_tickets(id),
            sender_id INTEGER NOT NULL, sender_role TEXT NOT NULL CHECK(sender_role IN ('guest','staff')),
            body TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        c.execute('CREATE INDEX IF NOT EXISTS ix_support_guest ON support_tickets(telegram_id,created_at)')
        c.execute('CREATE INDEX IF NOT EXISTS ix_support_thread ON support_messages(ticket_id,id)')
        c.execute("""CREATE TABLE IF NOT EXISTS dialogue_context (
            telegram_id INTEGER PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
            last_entity TEXT NOT NULL, last_intent TEXT NOT NULL, last_topic TEXT NOT NULL,
            updated_at TEXT NOT NULL, expires_at TEXT NOT NULL
        )""")


def mark_dirty(c):
    c.execute('UPDATE sync_jobs SET revision=revision+1,updated_at=? WHERE id=1', (utcnow(),))


def log(c, actor, action, entity_type, entity_id, details='{}'):
    c.execute('INSERT INTO audit(actor_id,action,entity_type,entity_id,details,created_at) VALUES (?,?,?,?,?,?)',
              (actor, action, entity_type, entity_id, details, utcnow()))
    mark_dirty(c)


def token_fingerprint(token: str) -> str:
    """One-way marker, never disclose the token itself in database or logs."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def bind_bot_identity():
    """Prevent silently reusing developer bot's users/admins/notifications for a client bot.

    When migrating a pre-v0.4 database the current bot is bound at first live start.
    Reuse a separate DATABASE_PATH for a new client, after backing up the old DB.
    """
    if not settings.bot_token:
        return
    fingerprint = token_fingerprint(settings.bot_token)
    with session(write=True) as c:
        row = c.execute('SELECT token_fingerprint FROM bot_identity WHERE id=1').fetchone()
        if row and row['token_fingerprint'] != fingerprint:
            raise RuntimeError('База данных принадлежит другому Telegram-боту. '
                               'Сохраните резервную копию и задайте новый DATABASE_PATH в .env '
                               '(например, data/tourist_client.sqlite3). Старые данные не удалены.')
        if row is None:
            c.execute('INSERT INTO bot_identity(id,token_fingerprint,created_at) VALUES (1,?,?)',
                      (fingerprint,utcnow()))


def assert_existing_bot_identity():
    """READ-ONLY gate: refuse someone else's bot DB BEFORE running migrations.

    Older v0.3 DBs had no identity marker, so first live binding is still possible.
    Never delete or reset data as an automatic response to a mismatch.
    """
    if not settings.bot_token:
        return
    db = database_path()
    if not db.exists():
        return
    with sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True) as connection:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_identity'").fetchone()
        if not exists:
            return
        row = connection.execute('SELECT token_fingerprint FROM bot_identity WHERE id=1').fetchone()
        if row and row[0] != token_fingerprint(settings.bot_token):
            raise RuntimeError('Остановлено до миграции: SQLite привязана к другому Telegram-боту. '
                               'Сделайте резервную копию и задайте отдельный DATABASE_PATH для нового бота.')


def initialize_storage():
    assert_existing_bot_identity()
    init_db()
    bind_bot_identity()
    # Opt-in showcase content: demo-labelled fixtures only, never silently insert
    # examples into a real client's schedule.
    if settings.showcase_mode:
        from app.service import ensure_showcase_schedule
        ensure_showcase_schedule()
