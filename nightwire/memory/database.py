"""SQLite database for memory storage with vector search support."""

import asyncio
import functools
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Any

import structlog

from .models import (
    User,
    Session,
    Conversation,
    Preference,
    ExplicitMemory,
    SearchResult,
)

logger = structlog.get_logger()

# Schema version for migrations
SCHEMA_VERSION = 4


def _locked(method):
    """Decorator to serialize all sync database access via threading.Lock.

    Prevents sqlite3.InterfaceError from concurrent thread access to
    the same connection when asyncio.to_thread dispatches to multiple
    thread pool workers simultaneously.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class DatabaseConnection:
    """Manages SQLite database connection and operations."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._has_vec: bool = False
        self._lock = threading.Lock()

    async def initialize(self) -> None:
        """Initialize the database with schema."""
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        """Synchronous initialization."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")

        # Check for sqlite-vec extension
        try:
            import sqlite_vec
            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            self._has_vec = True
            logger.info("sqlite_vec_loaded")
        except ImportError:
            logger.warning("sqlite_vec_not_available", error="sqlite-vec package not installed (pip install sqlite-vec)")
            self._has_vec = False
        except Exception as e:
            logger.warning("sqlite_vec_not_available", error=str(e))
            self._has_vec = False

        self._create_schema()
        logger.info("database_initialized", path=str(self.db_path), has_vec=self._has_vec)

    def _create_schema(self) -> None:
        """Create database tables."""
        cursor = self._conn.cursor()

        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                phone_number TEXT PRIMARY KEY,
                display_name TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_messages INTEGER DEFAULT 0
            )
        """)

        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                phone_number TEXT NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                project_name TEXT,
                summary TEXT,
                message_count INTEGER DEFAULT 0,
                FOREIGN KEY (phone_number) REFERENCES users(phone_number)
            )
        """)

        # Conversations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL,
                session_id TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                project_name TEXT,
                command_type TEXT,
                metadata TEXT,
                embedding_id INTEGER,
                FOREIGN KEY (phone_number) REFERENCES users(phone_number),
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)

        # Preferences table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                source_conversation_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP,
                use_count INTEGER DEFAULT 0,
                UNIQUE(phone_number, category, key),
                FOREIGN KEY (phone_number) REFERENCES users(phone_number),
                FOREIGN KEY (source_conversation_id) REFERENCES conversations(id)
            )
        """)

        # Explicit memories table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS explicit_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL,
                memory_text TEXT NOT NULL,
                tags TEXT,
                project_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                embedding_id INTEGER,
                FOREIGN KEY (phone_number) REFERENCES users(phone_number)
            )
        """)

        # Indexes for common queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_phone_time
            ON conversations(phone_number, timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_project
            ON conversations(phone_number, project_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_preferences_phone_category
            ON preferences(phone_number, category)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_phone
            ON sessions(phone_number)
        """)

        # Create vector table if sqlite-vec is available
        if self._has_vec:
            try:
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS embeddings USING vec0(
                        embedding float[384]
                    )
                """)
            except Exception as e:
                logger.warning("vec_table_creation_failed", error=str(e))

        # Schema version tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            )
        """)

        # Check current version and migrate if needed
        cursor.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        current_version = row[0] if row and row[0] else 0

        if current_version < 2:
            self._migrate_to_v2(cursor)

        if current_version < 3:
            self._migrate_to_v3(cursor)

        if current_version < 4:
            self._migrate_to_v4(cursor)

        # Update schema version
        cursor.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,)
        )

        self._conn.commit()

    def _migrate_to_v2(self, cursor: sqlite3.Cursor) -> None:
        """Migrate to schema version 2 - add autonomous task system tables."""
        logger.info("migrating_to_schema_v2")

        # PRDs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL,
                project_name TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK(status IN ('draft', 'active', 'completed', 'archived')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                metadata TEXT,
                FOREIGN KEY (phone_number) REFERENCES users(phone_number)
            )
        """)

        # Stories table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prd_id INTEGER NOT NULL,
                phone_number TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                acceptance_criteria TEXT,
                priority INTEGER DEFAULT 0,
                story_order INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'in_progress', 'completed', 'blocked', 'failed')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                embedding_id INTEGER,
                metadata TEXT,
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE CASCADE,
                FOREIGN KEY (phone_number) REFERENCES users(phone_number)
            )
        """)

        # Tasks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                story_id INTEGER NOT NULL,
                phone_number TEXT NOT NULL,
                project_name TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                task_order INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'queued', 'in_progress', 'running_tests',
                                     'completed', 'failed', 'blocked', 'cancelled')),
                priority INTEGER DEFAULT 0,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 2,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                error_message TEXT,
                claude_output TEXT,
                files_changed TEXT,
                quality_gate_results TEXT,
                embedding_id INTEGER,
                metadata TEXT,
                FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE,
                FOREIGN KEY (phone_number) REFERENCES users(phone_number)
            )
        """)

        # Learnings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL,
                project_name TEXT,
                task_id INTEGER,
                category TEXT NOT NULL
                    CHECK(category IN ('pattern', 'pitfall', 'best_practice', 'project_context',
                                       'debugging', 'architecture', 'testing', 'tool_usage')),
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                relevance_keywords TEXT,
                usage_count INTEGER DEFAULT 0,
                confidence REAL DEFAULT 1.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP,
                embedding_id INTEGER,
                is_active INTEGER DEFAULT 1,
                metadata TEXT,
                FOREIGN KEY (phone_number) REFERENCES users(phone_number),
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
            )
        """)

        # Indexes for autonomous system
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_prds_phone_project
            ON prds(phone_number, project_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_stories_prd
            ON stories(prd_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_stories_status
            ON stories(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_story
            ON tasks(story_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status
            ON tasks(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_queued
            ON tasks(status, priority DESC, task_order ASC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_learnings_phone_project
            ON learnings(phone_number, project_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_learnings_category
            ON learnings(category)
        """)

        logger.info("schema_v2_migration_complete")

    def _migrate_to_v3(self, cursor: sqlite3.Cursor) -> None:
        """Migrate to schema version 3 - add project_name to explicit_memories."""
        logger.info("migrating_to_schema_v3")

        # Add project_name column to explicit_memories if it doesn't exist
        try:
            cursor.execute("ALTER TABLE explicit_memories ADD COLUMN project_name TEXT")
        except sqlite3.OperationalError:
            # Column already exists
            pass

        # Add index for project-specific memory queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_phone_project
            ON explicit_memories(phone_number, project_name)
        """)

        logger.info("schema_v3_migration_complete")

    def _migrate_to_v4(self, cursor: sqlite3.Cursor) -> None:
        """Migrate to schema version 4 - add parallel execution fields to tasks."""
        logger.info("migrating_to_schema_v4")

        for col, col_type in [
            ("effort_level", "TEXT"),
            ("task_type", "TEXT"),
            ("depends_on", "TEXT"),
            ("verification_result", "TEXT"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE tasks ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass  # Column already exists

        logger.info("schema_v4_migration_complete")

    @property
    def has_vector_search(self) -> bool:
        """Check if vector search is available."""
        return self._has_vec

    def _parse_sqlite_timestamp(self, ts_str: Optional[str]) -> Optional[datetime]:
        """Parse SQLite CURRENT_TIMESTAMP format. Returns None for null input."""
        if not ts_str:
            return None
        try:
            # Try SQLite format first: 'YYYY-MM-DD HH:MM:SS'
            return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            # Fall back to ISO format
            return datetime.fromisoformat(ts_str)

    def _format_sqlite_timestamp(self, dt: datetime) -> str:
        """Format datetime for SQLite comparison."""
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await asyncio.to_thread(self._close_sync)

    @_locked
    def _close_sync(self) -> None:
        """Close connection under lock to prevent close-while-writing."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # User operations
    async def ensure_user(self, phone_number: str) -> User:
        """Get or create a user record."""
        return await asyncio.to_thread(self._ensure_user_sync, phone_number)

    @_locked
    def _ensure_user_sync(self, phone_number: str) -> User:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE phone_number = ?",
            (phone_number,)
        )
        row = cursor.fetchone()

        if row:
            return User(
                phone_number=row["phone_number"],
                display_name=row["display_name"],
                first_seen=self._parse_sqlite_timestamp(row["first_seen"]),
                last_active=self._parse_sqlite_timestamp(row["last_active"]),
                total_messages=row["total_messages"]
            )

        # Create new user
        cursor.execute(
            "INSERT INTO users (phone_number) VALUES (?)",
            (phone_number,)
        )
        self._conn.commit()
        return User(phone_number=phone_number)

    async def update_user_activity(self, phone_number: str) -> None:
        """Update user's last activity and message count."""
        await asyncio.to_thread(self._update_user_activity_sync, phone_number)

    @_locked
    def _update_user_activity_sync(self, phone_number: str) -> None:
        cursor = self._conn.cursor()
        cursor.execute("""
            UPDATE users
            SET last_active = CURRENT_TIMESTAMP, total_messages = total_messages + 1
            WHERE phone_number = ?
        """, (phone_number,))
        self._conn.commit()

    # Session operations
    async def get_or_create_session(
        self,
        phone_number: str,
        project_name: Optional[str] = None,
        timeout_minutes: int = 30
    ) -> Session:
        """Get current session or create a new one if expired."""
        return await asyncio.to_thread(
            self._get_or_create_session_sync,
            phone_number,
            project_name,
            timeout_minutes
        )

    @_locked
    def _get_or_create_session_sync(
        self,
        phone_number: str,
        project_name: Optional[str],
        timeout_minutes: int
    ) -> Session:
        cursor = self._conn.cursor()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

        # Find active session
        cursor.execute("""
            SELECT * FROM sessions
            WHERE phone_number = ? AND ended_at IS NULL AND started_at > ?
            ORDER BY started_at DESC LIMIT 1
        """, (phone_number, self._format_sqlite_timestamp(cutoff)))
        row = cursor.fetchone()

        if row:
            return Session(
                id=row["id"],
                phone_number=row["phone_number"],
                started_at=self._parse_sqlite_timestamp(row["started_at"]),
                project_name=row["project_name"],
                message_count=row["message_count"]
            )

        # Create new session
        session_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO sessions (id, phone_number, project_name)
            VALUES (?, ?, ?)
        """, (session_id, phone_number, project_name))
        self._conn.commit()

        return Session(
            id=session_id,
            phone_number=phone_number,
            project_name=project_name
        )

    async def update_session_count(self, session_id: str) -> None:
        """Increment session message count."""
        await asyncio.to_thread(self._update_session_count_sync, session_id)

    @_locked
    def _update_session_count_sync(self, session_id: str) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
            (session_id,)
        )
        self._conn.commit()

    # Conversation operations
    async def store_conversation(
        self,
        phone_number: str,
        session_id: str,
        role: str,
        content: str,
        project_name: Optional[str] = None,
        command_type: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None
    ) -> int:
        """Store a conversation message. Returns the conversation ID."""
        return await asyncio.to_thread(
            self._store_conversation_sync,
            phone_number,
            session_id,
            role,
            content,
            project_name,
            command_type,
            metadata
        )

    @_locked
    def _store_conversation_sync(
        self,
        phone_number: str,
        session_id: str,
        role: str,
        content: str,
        project_name: Optional[str],
        command_type: Optional[str],
        metadata: Optional[dict[str, Any]]
    ) -> int:
        cursor = self._conn.cursor()
        metadata_json = json.dumps(metadata) if metadata else None

        cursor.execute("""
            INSERT INTO conversations
            (phone_number, session_id, role, content, project_name, command_type, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (phone_number, session_id, role, content, project_name, command_type, metadata_json))
        self._conn.commit()

        return cursor.lastrowid

    async def get_history(
        self,
        phone_number: str,
        limit: int = 20,
        before: Optional[datetime] = None,
        project_name: Optional[str] = None
    ) -> List[Conversation]:
        """Get conversation history for a user."""
        return await asyncio.to_thread(
            self._get_history_sync,
            phone_number,
            limit,
            before,
            project_name
        )

    @_locked
    def _get_history_sync(
        self,
        phone_number: str,
        limit: int,
        before: Optional[datetime],
        project_name: Optional[str]
    ) -> List[Conversation]:
        cursor = self._conn.cursor()

        query = "SELECT * FROM conversations WHERE phone_number = ?"
        params: list = [phone_number]

        if before:
            query += " AND timestamp < ?"
            params.append(self._format_sqlite_timestamp(before))

        if project_name:
            query += " AND project_name = ?"
            params.append(project_name)

        # Sort by timestamp DESC, id DESC to get most recent first (id breaks ties)
        query += " ORDER BY timestamp DESC, id DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        conversations = []
        for row in rows:
            metadata = json.loads(row["metadata"]) if row["metadata"] else None
            conversations.append(Conversation(
                id=row["id"],
                phone_number=row["phone_number"],
                session_id=row["session_id"],
                timestamp=self._parse_sqlite_timestamp(row["timestamp"]),
                role=row["role"],
                content=row["content"],
                project_name=row["project_name"],
                command_type=row["command_type"],
                metadata=metadata,
                embedding_id=row["embedding_id"]
            ))

        # Return in chronological order (reverse the DESC order)
        return list(reversed(conversations))

    # Preference operations
    async def store_preference(
        self,
        phone_number: str,
        category: str,
        key: str,
        value: str,
        source_conversation_id: Optional[int] = None,
        confidence: float = 1.0
    ) -> int:
        """Store or update a user preference."""
        return await asyncio.to_thread(
            self._store_preference_sync,
            phone_number,
            category,
            key,
            value,
            source_conversation_id,
            confidence
        )

    @_locked
    def _store_preference_sync(
        self,
        phone_number: str,
        category: str,
        key: str,
        value: str,
        source_conversation_id: Optional[int],
        confidence: float
    ) -> int:
        cursor = self._conn.cursor()

        cursor.execute("""
            INSERT INTO preferences (phone_number, category, key, value, source_conversation_id, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(phone_number, category, key) DO UPDATE SET
                value = excluded.value,
                confidence = excluded.confidence,
                last_used = CURRENT_TIMESTAMP,
                use_count = use_count + 1
        """, (phone_number, category, key, value, source_conversation_id, confidence))
        self._conn.commit()

        return cursor.lastrowid

    async def get_preferences(
        self,
        phone_number: str,
        category: Optional[str] = None
    ) -> List[Preference]:
        """Get user preferences."""
        return await asyncio.to_thread(
            self._get_preferences_sync,
            phone_number,
            category
        )

    @_locked
    def _get_preferences_sync(
        self,
        phone_number: str,
        category: Optional[str]
    ) -> List[Preference]:
        cursor = self._conn.cursor()

        if category:
            cursor.execute(
                "SELECT * FROM preferences WHERE phone_number = ? AND category = ?",
                (phone_number, category)
            )
        else:
            cursor.execute(
                "SELECT * FROM preferences WHERE phone_number = ?",
                (phone_number,)
            )

        rows = cursor.fetchall()
        return [
            Preference(
                id=row["id"],
                phone_number=row["phone_number"],
                category=row["category"],
                key=row["key"],
                value=row["value"],
                confidence=row["confidence"],
                source_conversation_id=row["source_conversation_id"],
                created_at=self._parse_sqlite_timestamp(row["created_at"]),
                last_used=self._parse_sqlite_timestamp(row["last_used"]) if row["last_used"] else None,
                use_count=row["use_count"]
            )
            for row in rows
        ]

    # Explicit memory operations
    async def store_memory(
        self,
        phone_number: str,
        memory_text: str,
        tags: Optional[List[str]] = None,
        project_name: Optional[str] = None
    ) -> int:
        """Store an explicit memory from /remember command."""
        return await asyncio.to_thread(
            self._store_memory_sync,
            phone_number,
            memory_text,
            tags,
            project_name
        )

    @_locked
    def _store_memory_sync(
        self,
        phone_number: str,
        memory_text: str,
        tags: Optional[List[str]],
        project_name: Optional[str]
    ) -> int:
        cursor = self._conn.cursor()
        tags_json = json.dumps(tags) if tags else None

        cursor.execute("""
            INSERT INTO explicit_memories (phone_number, memory_text, tags, project_name)
            VALUES (?, ?, ?, ?)
        """, (phone_number, memory_text, tags_json, project_name))
        self._conn.commit()

        return cursor.lastrowid

    async def get_memories(
        self,
        phone_number: str,
        limit: int = 50,
        project_name: Optional[str] = None
    ) -> List[ExplicitMemory]:
        """Get explicit memories for a user, optionally filtered by project."""
        return await asyncio.to_thread(
            self._get_memories_sync,
            phone_number,
            limit,
            project_name
        )

    @_locked
    def _get_memories_sync(
        self,
        phone_number: str,
        limit: int,
        project_name: Optional[str]
    ) -> List[ExplicitMemory]:
        cursor = self._conn.cursor()

        if project_name:
            cursor.execute("""
                SELECT * FROM explicit_memories
                WHERE phone_number = ? AND project_name = ?
                ORDER BY created_at DESC LIMIT ?
            """, (phone_number, project_name, limit))
        else:
            cursor.execute("""
                SELECT * FROM explicit_memories
                WHERE phone_number = ?
                ORDER BY created_at DESC LIMIT ?
            """, (phone_number, limit))

        rows = cursor.fetchall()
        return [
            ExplicitMemory(
                id=row["id"],
                phone_number=row["phone_number"],
                memory_text=row["memory_text"],
                tags=json.loads(row["tags"]) if row["tags"] else None,
                created_at=self._parse_sqlite_timestamp(row["created_at"]),
                embedding_id=row["embedding_id"],
                project_name=row["project_name"] if "project_name" in row.keys() else None
            )
            for row in rows
        ]

    # Deletion operations
    async def delete_all_user_data(self, phone_number: str) -> int:
        """Delete all data for a user. Returns count of deleted records."""
        return await asyncio.to_thread(self._delete_all_user_data_sync, phone_number)

    @_locked
    def _delete_all_user_data_sync(self, phone_number: str) -> int:
        cursor = self._conn.cursor()
        total = 0

        # Delete orphaned embeddings first (before removing the referencing rows)
        if self._has_vec:
            try:
                cursor.execute("""
                    DELETE FROM embeddings WHERE rowid IN (
                        SELECT embedding_id FROM conversations
                        WHERE phone_number = ? AND embedding_id IS NOT NULL
                        UNION
                        SELECT embedding_id FROM explicit_memories
                        WHERE phone_number = ? AND embedding_id IS NOT NULL
                    )
                """, (phone_number, phone_number))
                total += cursor.rowcount
            except Exception:
                pass  # Vector table may not exist; proceed with data deletion

        cursor.execute("DELETE FROM conversations WHERE phone_number = ?", (phone_number,))
        total += cursor.rowcount

        cursor.execute("DELETE FROM preferences WHERE phone_number = ?", (phone_number,))
        total += cursor.rowcount

        cursor.execute("DELETE FROM explicit_memories WHERE phone_number = ?", (phone_number,))
        total += cursor.rowcount

        # Delete autonomous system data
        cursor.execute("DELETE FROM learnings WHERE phone_number = ?", (phone_number,))
        total += cursor.rowcount
        cursor.execute("DELETE FROM tasks WHERE phone_number = ?", (phone_number,))
        total += cursor.rowcount
        cursor.execute("DELETE FROM stories WHERE phone_number = ?", (phone_number,))
        total += cursor.rowcount
        cursor.execute("DELETE FROM prds WHERE phone_number = ?", (phone_number,))
        total += cursor.rowcount

        cursor.execute("DELETE FROM sessions WHERE phone_number = ?", (phone_number,))
        total += cursor.rowcount

        cursor.execute("DELETE FROM users WHERE phone_number = ?", (phone_number,))
        total += cursor.rowcount

        self._conn.commit()
        return total

    async def delete_preferences(self, phone_number: str) -> int:
        """Delete all preferences for a user."""
        return await asyncio.to_thread(self._delete_preferences_sync, phone_number)

    @_locked
    def _delete_preferences_sync(self, phone_number: str) -> int:
        cursor = self._conn.cursor()
        cursor.execute("DELETE FROM preferences WHERE phone_number = ?", (phone_number,))
        self._conn.commit()
        return cursor.rowcount

    async def delete_today_conversations(self, phone_number: str) -> int:
        """Delete today's conversations for a user."""
        return await asyncio.to_thread(self._delete_today_sync, phone_number)

    @_locked
    def _delete_today_sync(self, phone_number: str) -> int:
        cursor = self._conn.cursor()
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        cursor.execute("""
            DELETE FROM conversations
            WHERE phone_number = ? AND timestamp >= ?
        """, (phone_number, self._format_sqlite_timestamp(today)))
        self._conn.commit()
        return cursor.rowcount

    # Embedding operations (for vector search)
    async def store_embedding(self, embedding: List[float]) -> Optional[int]:
        """Store an embedding vector. Returns embedding ID or None if vec not available."""
        if not self._has_vec:
            return None
        return await asyncio.to_thread(self._store_embedding_sync, embedding)

    @_locked
    def _store_embedding_sync(self, embedding: List[float]) -> int:
        cursor = self._conn.cursor()
        cursor.execute(
            "INSERT INTO embeddings (embedding) VALUES (?)",
            (json.dumps(embedding),)
        )
        self._conn.commit()
        return cursor.lastrowid

    async def update_conversation_embedding(
        self,
        conversation_id: int,
        embedding_id: int
    ) -> None:
        """Link a conversation to its embedding."""
        await asyncio.to_thread(
            self._update_conversation_embedding_sync,
            conversation_id,
            embedding_id
        )

    @_locked
    def _update_conversation_embedding_sync(
        self,
        conversation_id: int,
        embedding_id: int
    ) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            "UPDATE conversations SET embedding_id = ? WHERE id = ?",
            (embedding_id, conversation_id)
        )
        self._conn.commit()

    async def search_by_embedding(
        self,
        phone_number: str,
        query_embedding: List[float],
        limit: int = 10
    ) -> List[SearchResult]:
        """Search conversations by embedding similarity."""
        if not self._has_vec:
            return []
        return await asyncio.to_thread(
            self._search_by_embedding_sync,
            phone_number,
            query_embedding,
            limit
        )

    @_locked
    def _search_by_embedding_sync(
        self,
        phone_number: str,
        query_embedding: List[float],
        limit: int
    ) -> List[SearchResult]:
        cursor = self._conn.cursor()

        # Join embeddings with conversations and filter by user
        cursor.execute("""
            SELECT c.id, c.content, c.role, c.timestamp, c.project_name,
                   vec_distance_cosine(e.embedding, ?) as distance
            FROM conversations c
            JOIN embeddings e ON c.embedding_id = e.rowid
            WHERE c.phone_number = ?
            ORDER BY distance ASC
            LIMIT ?
        """, (json.dumps(query_embedding), phone_number, limit))

        rows = cursor.fetchall()
        return [
            SearchResult(
                id=row["id"],
                content=row["content"],
                role=row["role"],
                timestamp=self._parse_sqlite_timestamp(row["timestamp"]) or datetime.now(timezone.utc),
                project_name=row["project_name"],
                similarity_score=max(0.0, min(1.0, 1 - row["distance"])),  # Clamp to [0, 1]
                source_type="conversation"
            )
            for row in rows
        ]


# Global database instance
_db: Optional[DatabaseConnection] = None


def get_database(db_path: Optional[Path] = None) -> DatabaseConnection:
    """Get or create the global database instance."""
    global _db
    if _db is None:
        if db_path is None:
            raise ValueError("db_path required for first initialization")
        _db = DatabaseConnection(db_path)
    return _db


async def initialize_database(db_path: Path) -> DatabaseConnection:
    """Initialize and return the database."""
    global _db
    if _db is not None:
        try:
            await _db.close()
        except Exception:
            pass
    _db = DatabaseConnection(db_path)
    await _db.initialize()
    return _db
