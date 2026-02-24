"""Database operations for the autonomous task system."""

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Any

import structlog

from .models import (
    PRD,
    PRDStatus,
    Story,
    StoryStatus,
    Task,
    TaskStatus,
    Learning,
    LearningCategory,
    QualityGateResult,
    VerificationResult,
    EffortLevel,
    TaskType,
)

logger = structlog.get_logger()


class AutonomousDatabase:
    """Database operations for autonomous task management.

    Note: Task/PRD/Story access is not scoped by phone number.
    All authorized users share the same workspace — this is by design.
    Authorization is enforced at the Signal message entry point (security.py).
    """

    def __init__(self, conn: sqlite3.Connection):
        """Initialize with existing database connection from memory system."""
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    def _parse_timestamp(self, ts_str: Optional[str]) -> Optional[datetime]:
        """Parse SQLite timestamp format."""
        if not ts_str:
            return None
        try:
            return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                return datetime.fromisoformat(ts_str)
            except ValueError:
                return None

    def _format_timestamp(self, dt: Optional[datetime]) -> Optional[str]:
        """Format datetime for SQLite."""
        if not dt:
            return None
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    # ========== PRD Operations ==========

    async def create_prd(
        self,
        phone_number: str,
        project_name: str,
        title: str,
        description: str,
        status: PRDStatus = PRDStatus.DRAFT,
        metadata: Optional[dict[str, Any]] = None,
    ) -> PRD:
        """Create a new PRD."""
        return await asyncio.to_thread(
            self._create_prd_sync,
            phone_number,
            project_name,
            title,
            description,
            status,
            metadata,
        )

    def _create_prd_sync(
        self,
        phone_number: str,
        project_name: str,
        title: str,
        description: str,
        status: PRDStatus,
        metadata: Optional[dict[str, Any]],
    ) -> PRD:
        cursor = self._conn.cursor()
        metadata_json = json.dumps(metadata) if metadata else None

        cursor.execute(
            """
            INSERT INTO prds (phone_number, project_name, title, description, status, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (phone_number, project_name, title, description, status.value, metadata_json),
        )
        self._conn.commit()

        return PRD(
            id=cursor.lastrowid,
            phone_number=phone_number,
            project_name=project_name,
            title=title,
            description=description,
            status=status,
            metadata=metadata,
        )

    async def get_prd(self, prd_id: int) -> Optional[PRD]:
        """Get a PRD by ID with story counts."""
        return await asyncio.to_thread(self._get_prd_sync, prd_id)

    def _get_prd_sync(self, prd_id: int) -> Optional[PRD]:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT p.*,
                   COUNT(s.id) as total_stories,
                   SUM(CASE WHEN s.status = 'completed' THEN 1 ELSE 0 END) as completed_stories,
                   SUM(CASE WHEN s.status = 'failed' THEN 1 ELSE 0 END) as failed_stories
            FROM prds p
            LEFT JOIN stories s ON s.prd_id = p.id
            WHERE p.id = ?
            GROUP BY p.id
        """,
            (prd_id,),
        )
        row = cursor.fetchone()

        if not row:
            return None

        return PRD(
            id=row["id"],
            phone_number=row["phone_number"],
            project_name=row["project_name"],
            title=row["title"],
            description=row["description"],
            status=PRDStatus(row["status"]),
            created_at=self._parse_timestamp(row["created_at"]) or datetime.now(),
            updated_at=self._parse_timestamp(row["updated_at"]) or datetime.now(),
            completed_at=self._parse_timestamp(row["completed_at"]),
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            total_stories=row["total_stories"] or 0,
            completed_stories=row["completed_stories"] or 0,
            failed_stories=row["failed_stories"] or 0,
        )

    async def list_prds(
        self,
        phone_number: str,
        project_name: Optional[str] = None,
        status: Optional[PRDStatus] = None,
    ) -> List[PRD]:
        """List PRDs for a user."""
        return await asyncio.to_thread(
            self._list_prds_sync, phone_number, project_name, status
        )

    def _list_prds_sync(
        self,
        phone_number: str,
        project_name: Optional[str],
        status: Optional[PRDStatus],
    ) -> List[PRD]:
        cursor = self._conn.cursor()

        query = """
            SELECT p.*,
                   COUNT(s.id) as total_stories,
                   SUM(CASE WHEN s.status = 'completed' THEN 1 ELSE 0 END) as completed_stories,
                   SUM(CASE WHEN s.status = 'failed' THEN 1 ELSE 0 END) as failed_stories
            FROM prds p
            LEFT JOIN stories s ON s.prd_id = p.id
            WHERE p.phone_number = ?
        """
        params: list = [phone_number]

        if project_name:
            query += " AND p.project_name = ?"
            params.append(project_name)

        if status:
            query += " AND p.status = ?"
            params.append(status.value)

        query += " GROUP BY p.id ORDER BY p.created_at DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            PRD(
                id=row["id"],
                phone_number=row["phone_number"],
                project_name=row["project_name"],
                title=row["title"],
                description=row["description"],
                status=PRDStatus(row["status"]),
                created_at=self._parse_timestamp(row["created_at"]) or datetime.now(),
                updated_at=self._parse_timestamp(row["updated_at"]) or datetime.now(),
                completed_at=self._parse_timestamp(row["completed_at"]),
                metadata=json.loads(row["metadata"]) if row["metadata"] else None,
                total_stories=row["total_stories"] or 0,
                completed_stories=row["completed_stories"] or 0,
                failed_stories=row["failed_stories"] or 0,
            )
            for row in rows
        ]

    async def update_prd_status(
        self, prd_id: int, status: PRDStatus
    ) -> None:
        """Update PRD status."""
        await asyncio.to_thread(self._update_prd_status_sync, prd_id, status)

    def _update_prd_status_sync(self, prd_id: int, status: PRDStatus) -> None:
        cursor = self._conn.cursor()
        completed_at = (
            self._format_timestamp(datetime.now())
            if status == PRDStatus.COMPLETED
            else None
        )

        cursor.execute(
            """
            UPDATE prds
            SET status = ?, updated_at = CURRENT_TIMESTAMP, completed_at = ?
            WHERE id = ?
        """,
            (status.value, completed_at, prd_id),
        )
        self._conn.commit()

    # ========== Story Operations ==========

    async def create_story(
        self,
        prd_id: int,
        phone_number: str,
        title: str,
        description: str,
        acceptance_criteria: Optional[List[str]] = None,
        priority: int = 0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Story:
        """Create a new story."""
        return await asyncio.to_thread(
            self._create_story_sync,
            prd_id,
            phone_number,
            title,
            description,
            acceptance_criteria,
            priority,
            metadata,
        )

    def _create_story_sync(
        self,
        prd_id: int,
        phone_number: str,
        title: str,
        description: str,
        acceptance_criteria: Optional[List[str]],
        priority: int,
        metadata: Optional[dict[str, Any]],
    ) -> Story:
        cursor = self._conn.cursor()

        # Get next story order
        cursor.execute(
            "SELECT COALESCE(MAX(story_order), -1) + 1 FROM stories WHERE prd_id = ?",
            (prd_id,),
        )
        story_order = cursor.fetchone()[0]

        ac_json = json.dumps(acceptance_criteria) if acceptance_criteria else None
        metadata_json = json.dumps(metadata) if metadata else None

        cursor.execute(
            """
            INSERT INTO stories
            (prd_id, phone_number, title, description, acceptance_criteria, priority, story_order, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                prd_id,
                phone_number,
                title,
                description,
                ac_json,
                priority,
                story_order,
                metadata_json,
            ),
        )
        self._conn.commit()

        return Story(
            id=cursor.lastrowid,
            prd_id=prd_id,
            phone_number=phone_number,
            title=title,
            description=description,
            acceptance_criteria=acceptance_criteria,
            priority=priority,
            story_order=story_order,
            metadata=metadata,
        )

    async def get_story(self, story_id: int) -> Optional[Story]:
        """Get a story by ID with task counts."""
        return await asyncio.to_thread(self._get_story_sync, story_id)

    def _get_story_sync(self, story_id: int) -> Optional[Story]:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT s.*,
                   COUNT(t.id) as total_tasks,
                   SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) as completed_tasks,
                   SUM(CASE WHEN t.status = 'failed' THEN 1 ELSE 0 END) as failed_tasks
            FROM stories s
            LEFT JOIN tasks t ON t.story_id = s.id
            WHERE s.id = ?
            GROUP BY s.id
        """,
            (story_id,),
        )
        row = cursor.fetchone()

        if not row:
            return None

        return Story(
            id=row["id"],
            prd_id=row["prd_id"],
            phone_number=row["phone_number"],
            title=row["title"],
            description=row["description"],
            acceptance_criteria=(
                json.loads(row["acceptance_criteria"])
                if row["acceptance_criteria"]
                else None
            ),
            priority=row["priority"],
            story_order=row["story_order"],
            status=StoryStatus(row["status"]),
            created_at=self._parse_timestamp(row["created_at"]) or datetime.now(),
            updated_at=self._parse_timestamp(row["updated_at"]) or datetime.now(),
            completed_at=self._parse_timestamp(row["completed_at"]),
            embedding_id=row["embedding_id"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            total_tasks=row["total_tasks"] or 0,
            completed_tasks=row["completed_tasks"] or 0,
            failed_tasks=row["failed_tasks"] or 0,
        )

    async def list_stories(
        self,
        prd_id: Optional[int] = None,
        phone_number: Optional[str] = None,
        status: Optional[StoryStatus] = None,
    ) -> List[Story]:
        """List stories with optional filters."""
        return await asyncio.to_thread(
            self._list_stories_sync, prd_id, phone_number, status
        )

    def _list_stories_sync(
        self,
        prd_id: Optional[int],
        phone_number: Optional[str],
        status: Optional[StoryStatus],
    ) -> List[Story]:
        cursor = self._conn.cursor()

        query = """
            SELECT s.*,
                   COUNT(t.id) as total_tasks,
                   SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) as completed_tasks,
                   SUM(CASE WHEN t.status = 'failed' THEN 1 ELSE 0 END) as failed_tasks
            FROM stories s
            LEFT JOIN tasks t ON t.story_id = s.id
            WHERE 1=1
        """
        params: list = []

        if prd_id:
            query += " AND s.prd_id = ?"
            params.append(prd_id)

        if phone_number:
            query += " AND s.phone_number = ?"
            params.append(phone_number)

        if status:
            query += " AND s.status = ?"
            params.append(status.value)

        query += " GROUP BY s.id ORDER BY s.priority DESC, s.story_order ASC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            Story(
                id=row["id"],
                prd_id=row["prd_id"],
                phone_number=row["phone_number"],
                title=row["title"],
                description=row["description"],
                acceptance_criteria=(
                    json.loads(row["acceptance_criteria"])
                    if row["acceptance_criteria"]
                    else None
                ),
                priority=row["priority"],
                story_order=row["story_order"],
                status=StoryStatus(row["status"]),
                created_at=self._parse_timestamp(row["created_at"]) or datetime.now(),
                updated_at=self._parse_timestamp(row["updated_at"]) or datetime.now(),
                completed_at=self._parse_timestamp(row["completed_at"]),
                embedding_id=row["embedding_id"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else None,
                total_tasks=row["total_tasks"] or 0,
                completed_tasks=row["completed_tasks"] or 0,
                failed_tasks=row["failed_tasks"] or 0,
            )
            for row in rows
        ]

    async def update_story_status(self, story_id: int, status: StoryStatus) -> None:
        """Update story status."""
        await asyncio.to_thread(self._update_story_status_sync, story_id, status)

    def _update_story_status_sync(self, story_id: int, status: StoryStatus) -> None:
        cursor = self._conn.cursor()
        completed_at = (
            self._format_timestamp(datetime.now())
            if status == StoryStatus.COMPLETED
            else None
        )

        cursor.execute(
            """
            UPDATE stories
            SET status = ?, updated_at = CURRENT_TIMESTAMP, completed_at = ?
            WHERE id = ?
        """,
            (status.value, completed_at, story_id),
        )
        self._conn.commit()

    # ========== Task Operations ==========

    async def create_task(
        self,
        story_id: int,
        phone_number: str,
        project_name: str,
        title: str,
        description: str,
        priority: int = 0,
        max_retries: int = 2,
        metadata: Optional[dict[str, Any]] = None,
        depends_on: Optional[list] = None,
        task_type: Optional[str] = None,
        effort_level: Optional[str] = None,
    ) -> Task:
        """Create a new task."""
        return await asyncio.to_thread(
            self._create_task_sync,
            story_id,
            phone_number,
            project_name,
            title,
            description,
            priority,
            max_retries,
            metadata,
            depends_on,
            task_type,
            effort_level,
        )

    def _create_task_sync(
        self,
        story_id: int,
        phone_number: str,
        project_name: str,
        title: str,
        description: str,
        priority: int,
        max_retries: int,
        metadata: Optional[dict[str, Any]],
        depends_on: Optional[list] = None,
        task_type: Optional[str] = None,
        effort_level: Optional[str] = None,
    ) -> Task:
        cursor = self._conn.cursor()

        # Get next task order
        cursor.execute(
            "SELECT COALESCE(MAX(task_order), -1) + 1 FROM tasks WHERE story_id = ?",
            (story_id,),
        )
        task_order = cursor.fetchone()[0]

        metadata_json = json.dumps(metadata) if metadata else None
        depends_on_json = json.dumps(depends_on) if depends_on is not None else None

        cursor.execute(
            """
            INSERT INTO tasks
            (story_id, phone_number, project_name, title, description, priority, task_order,
             max_retries, metadata, depends_on, task_type, effort_level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                story_id,
                phone_number,
                project_name,
                title,
                description,
                priority,
                task_order,
                max_retries,
                metadata_json,
                depends_on_json,
                task_type,
                effort_level,
            ),
        )
        self._conn.commit()

        # Convert string values to enums for the Task model, matching _row_to_task() behavior
        effort_level_enum = None
        if effort_level:
            try:
                effort_level_enum = EffortLevel(effort_level)
            except ValueError:
                pass

        task_type_enum = None
        if task_type:
            try:
                task_type_enum = TaskType(task_type)
            except ValueError:
                pass

        return Task(
            id=cursor.lastrowid,
            story_id=story_id,
            phone_number=phone_number,
            project_name=project_name,
            title=title,
            description=description,
            priority=priority,
            task_order=task_order,
            max_retries=max_retries,
            metadata=metadata,
            depends_on=depends_on,
            task_type=task_type_enum,
            effort_level=effort_level_enum,
        )

    async def get_task(self, task_id: int) -> Optional[Task]:
        """Get a task by ID."""
        return await asyncio.to_thread(self._get_task_sync, task_id)

    def _get_task_sync(self, task_id: int) -> Optional[Task]:
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()

        if not row:
            return None

        return self._row_to_task(row)

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        """Convert a database row to a Task model."""
        # Safely access new columns that may not exist in older schemas
        row_keys = row.keys()

        effort_level = None
        if "effort_level" in row_keys and row["effort_level"]:
            try:
                effort_level = EffortLevel(row["effort_level"])
            except ValueError:
                pass

        task_type = None
        if "task_type" in row_keys and row["task_type"]:
            try:
                task_type = TaskType(row["task_type"])
            except ValueError:
                pass

        depends_on = None
        if "depends_on" in row_keys and row["depends_on"]:
            depends_on = json.loads(row["depends_on"])

        verification_result = None
        if "verification_result" in row_keys and row["verification_result"]:
            verification_result = json.loads(row["verification_result"])

        return Task(
            id=row["id"],
            story_id=row["story_id"],
            phone_number=row["phone_number"],
            project_name=row["project_name"],
            title=row["title"],
            description=row["description"],
            task_order=row["task_order"],
            status=TaskStatus(row["status"]),
            priority=row["priority"],
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            effort_level=effort_level,
            task_type=task_type,
            depends_on=depends_on,
            created_at=self._parse_timestamp(row["created_at"]) or datetime.now(),
            started_at=self._parse_timestamp(row["started_at"]),
            completed_at=self._parse_timestamp(row["completed_at"]),
            error_message=row["error_message"],
            claude_output=row["claude_output"],
            files_changed=(
                json.loads(row["files_changed"]) if row["files_changed"] else None
            ),
            quality_gate_results=(
                json.loads(row["quality_gate_results"])
                if row["quality_gate_results"]
                else None
            ),
            verification_result=verification_result,
            embedding_id=row["embedding_id"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
        )

    async def list_tasks(
        self,
        story_id: Optional[int] = None,
        phone_number: Optional[str] = None,
        project_name: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
    ) -> List[Task]:
        """List tasks with optional filters."""
        return await asyncio.to_thread(
            self._list_tasks_sync, story_id, phone_number, project_name, status, limit
        )

    def _list_tasks_sync(
        self,
        story_id: Optional[int],
        phone_number: Optional[str],
        project_name: Optional[str],
        status: Optional[TaskStatus],
        limit: int,
    ) -> List[Task]:
        cursor = self._conn.cursor()

        query = "SELECT * FROM tasks WHERE 1=1"
        params: list = []

        if story_id:
            query += " AND story_id = ?"
            params.append(story_id)

        if phone_number:
            query += " AND phone_number = ?"
            params.append(phone_number)

        if project_name:
            query += " AND project_name = ?"
            params.append(project_name)

        if status:
            query += " AND status = ?"
            params.append(status.value)

        query += " ORDER BY priority DESC, task_order ASC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [self._row_to_task(row) for row in rows]

    async def get_next_queued_task(self) -> Optional[Task]:
        """Get the next task in queue (highest priority, lowest order)."""
        return await asyncio.to_thread(self._get_next_queued_task_sync)

    def _get_next_queued_task_sync(self) -> Optional[Task]:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT * FROM tasks
            WHERE status = ?
            ORDER BY priority DESC, task_order ASC
            LIMIT 1
        """,
            (TaskStatus.QUEUED.value,),
        )
        row = cursor.fetchone()

        if not row:
            return None

        return self._row_to_task(row)

    async def get_queued_task_count(self) -> int:
        """Get count of queued tasks."""
        return await asyncio.to_thread(self._get_queued_task_count_sync)

    def _get_queued_task_count_sync(self) -> int:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = ?", (TaskStatus.QUEUED.value,)
        )
        return cursor.fetchone()[0]

    async def update_task_status(
        self,
        task_id: int,
        status: TaskStatus,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
        claude_output: Optional[str] = None,
        files_changed: Optional[List[str]] = None,
        quality_gate_results: Optional[QualityGateResult] = None,
    ) -> None:
        """Update task status and related fields."""
        await asyncio.to_thread(
            self._update_task_status_sync,
            task_id,
            status,
            started_at,
            completed_at,
            error_message,
            claude_output,
            files_changed,
            quality_gate_results,
        )

    def _update_task_status_sync(
        self,
        task_id: int,
        status: TaskStatus,
        started_at: Optional[datetime],
        completed_at: Optional[datetime],
        error_message: Optional[str],
        claude_output: Optional[str],
        files_changed: Optional[List[str]],
        quality_gate_results: Optional[QualityGateResult],
    ) -> None:
        cursor = self._conn.cursor()

        files_json = json.dumps(files_changed) if files_changed else None
        qg_json = (
            json.dumps(quality_gate_results.model_dump())
            if quality_gate_results
            else None
        )

        # When requeueing for retry, clear execution-specific fields so stale
        # data from the previous attempt doesn't persist via COALESCE.
        if status == TaskStatus.QUEUED:
            cursor.execute(
                """
                UPDATE tasks
                SET status = ?,
                    started_at = NULL,
                    completed_at = NULL,
                    error_message = ?,
                    claude_output = NULL,
                    files_changed = NULL,
                    quality_gate_results = NULL
                WHERE id = ?
            """,
                (status.value, error_message, task_id),
            )
        else:
            cursor.execute(
                """
                UPDATE tasks
                SET status = ?,
                    started_at = COALESCE(?, started_at),
                    completed_at = COALESCE(?, completed_at),
                    error_message = COALESCE(?, error_message),
                    claude_output = COALESCE(?, claude_output),
                    files_changed = COALESCE(?, files_changed),
                    quality_gate_results = COALESCE(?, quality_gate_results)
                WHERE id = ?
            """,
                (
                    status.value,
                    self._format_timestamp(started_at),
                    self._format_timestamp(completed_at),
                    error_message,
                    claude_output,
                    files_json,
                    qg_json,
                    task_id,
                ),
            )
        self._conn.commit()

    async def store_verification_result(
        self, task_id: int, verification: VerificationResult
    ) -> None:
        """Store verification result for a task."""
        await asyncio.to_thread(
            self._store_verification_result_sync, task_id, verification
        )

    def _store_verification_result_sync(
        self, task_id: int, verification: VerificationResult
    ) -> None:
        cursor = self._conn.cursor()
        vr_json = json.dumps(verification.model_dump())
        cursor.execute(
            "UPDATE tasks SET verification_result = ? WHERE id = ?",
            (vr_json, task_id),
        )
        self._conn.commit()

    async def increment_retry_count(self, task_id: int) -> None:
        """Increment task retry count."""
        await asyncio.to_thread(self._increment_retry_count_sync, task_id)

    def _increment_retry_count_sync(self, task_id: int) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            "UPDATE tasks SET retry_count = retry_count + 1 WHERE id = ?", (task_id,)
        )
        self._conn.commit()

    async def queue_tasks_for_story(self, story_id: int) -> int:
        """Queue all pending tasks for a story. Returns count queued."""
        return await asyncio.to_thread(self._queue_tasks_for_story_sync, story_id)

    def _queue_tasks_for_story_sync(self, story_id: int) -> int:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            UPDATE tasks
            SET status = ?
            WHERE story_id = ? AND status = ?
        """,
            (TaskStatus.QUEUED.value, story_id, TaskStatus.PENDING.value),
        )
        self._conn.commit()
        return cursor.rowcount

    async def queue_tasks_for_prd(self, prd_id: int) -> int:
        """Queue all pending tasks for all stories in a PRD. Returns count queued."""
        return await asyncio.to_thread(self._queue_tasks_for_prd_sync, prd_id)

    def _queue_tasks_for_prd_sync(self, prd_id: int) -> int:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            UPDATE tasks
            SET status = ?
            WHERE story_id IN (SELECT id FROM stories WHERE prd_id = ?)
            AND status = ?
        """,
            (TaskStatus.QUEUED.value, prd_id, TaskStatus.PENDING.value),
        )
        self._conn.commit()
        return cursor.rowcount

    # ========== Learning Operations ==========

    async def store_learning(self, learning: Learning) -> int:
        """Store a learning. Returns learning ID."""
        return await asyncio.to_thread(self._store_learning_sync, learning)

    def _store_learning_sync(self, learning: Learning) -> int:
        cursor = self._conn.cursor()

        keywords_json = (
            json.dumps(learning.relevance_keywords) if learning.relevance_keywords else None
        )
        metadata_json = json.dumps(learning.metadata) if learning.metadata else None

        cursor.execute(
            """
            INSERT INTO learnings
            (phone_number, project_name, task_id, category, title, content,
             relevance_keywords, confidence, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                learning.phone_number,
                learning.project_name,
                learning.task_id,
                learning.category.value,
                learning.title,
                learning.content,
                keywords_json,
                learning.confidence,
                metadata_json,
            ),
        )
        self._conn.commit()

        return cursor.lastrowid

    async def get_learnings(
        self,
        phone_number: str,
        project_name: Optional[str] = None,
        category: Optional[LearningCategory] = None,
        limit: int = 50,
    ) -> List[Learning]:
        """Get learnings with optional filters."""
        return await asyncio.to_thread(
            self._get_learnings_sync, phone_number, project_name, category, limit
        )

    def _get_learnings_sync(
        self,
        phone_number: str,
        project_name: Optional[str],
        category: Optional[LearningCategory],
        limit: int,
    ) -> List[Learning]:
        cursor = self._conn.cursor()

        query = "SELECT * FROM learnings WHERE phone_number = ? AND is_active = 1"
        params: list = [phone_number]

        if project_name:
            query += " AND (project_name = ? OR project_name IS NULL)"
            params.append(project_name)

        if category:
            query += " AND category = ?"
            params.append(category.value)

        query += " ORDER BY confidence DESC, usage_count DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [self._row_to_learning(row) for row in rows]

    def _row_to_learning(self, row: sqlite3.Row) -> Learning:
        """Convert a database row to a Learning model."""
        return Learning(
            id=row["id"],
            phone_number=row["phone_number"],
            project_name=row["project_name"],
            task_id=row["task_id"],
            category=LearningCategory(row["category"]),
            title=row["title"],
            content=row["content"],
            relevance_keywords=(
                json.loads(row["relevance_keywords"])
                if row["relevance_keywords"]
                else None
            ),
            usage_count=row["usage_count"],
            confidence=row["confidence"],
            created_at=self._parse_timestamp(row["created_at"]) or datetime.now(),
            last_used=self._parse_timestamp(row["last_used"]),
            embedding_id=row["embedding_id"],
            is_active=bool(row["is_active"]),
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
        )

    async def get_relevant_learnings(
        self,
        phone_number: str,
        project_name: Optional[str],
        query: str,
        limit: int = 10,
    ) -> List[Learning]:
        """Get learnings relevant to a query using keyword matching."""
        return await asyncio.to_thread(
            self._get_relevant_learnings_sync, phone_number, project_name, query, limit
        )

    def _get_relevant_learnings_sync(
        self,
        phone_number: str,
        project_name: Optional[str],
        query: str,
        limit: int,
    ) -> List[Learning]:
        """Get learnings using keyword matching (fallback without embeddings)."""
        cursor = self._conn.cursor()

        # Get all active learnings for this user/project
        sql = """
            SELECT * FROM learnings
            WHERE phone_number = ? AND is_active = 1
        """
        params: list = [phone_number]

        if project_name:
            sql += " AND (project_name = ? OR project_name IS NULL)"
            params.append(project_name)

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        # Score each learning based on keyword overlap
        query_words = set(query.lower().split())
        if not query_words:
            return []
        scored_learnings = []

        for row in rows:
            learning = self._row_to_learning(row)

            # Calculate relevance score
            score = 0.0
            content_words = set(learning.content.lower().split())
            title_words = set(learning.title.lower().split())

            # Title matches weighted higher
            title_overlap = len(query_words & title_words)
            content_overlap = len(query_words & content_words)

            if title_overlap > 0:
                score += 0.5 * title_overlap / len(query_words)
            if content_overlap > 0:
                score += 0.3 * content_overlap / len(query_words)

            # Keyword matches
            if learning.relevance_keywords:
                keyword_set = set(k.lower() for k in learning.relevance_keywords)
                keyword_overlap = len(query_words & keyword_set)
                if keyword_overlap > 0:
                    score += 0.2 * keyword_overlap / len(query_words)

            # Boost by confidence and usage
            score *= learning.confidence
            score *= 1 + (learning.usage_count * 0.05)  # Small boost per usage

            if score > 0.1:  # Threshold
                scored_learnings.append((score, learning))

        # Sort by score and return top results
        scored_learnings.sort(key=lambda x: x[0], reverse=True)
        return [learning for score, learning in scored_learnings[:limit]]

    async def increment_learning_usage(self, learning_id: int) -> None:
        """Increment learning usage count and update last_used."""
        await asyncio.to_thread(self._increment_learning_usage_sync, learning_id)

    def _increment_learning_usage_sync(self, learning_id: int) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            UPDATE learnings
            SET usage_count = usage_count + 1, last_used = CURRENT_TIMESTAMP
            WHERE id = ?
        """,
            (learning_id,),
        )
        self._conn.commit()

    async def decay_unused_learnings(self, days_threshold: int = 30) -> int:
        """Decay confidence of unused learnings. Returns count affected."""
        return await asyncio.to_thread(
            self._decay_unused_learnings_sync, days_threshold
        )

    def _decay_unused_learnings_sync(self, days_threshold: int) -> int:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            UPDATE learnings
            SET confidence = confidence * 0.9
            WHERE (last_used IS NULL OR last_used < datetime('now', ?))
            AND confidence > 0.1
            AND is_active = 1
        """,
            (f"-{days_threshold} days",),
        )
        self._conn.commit()
        return cursor.rowcount

    # ========== Statistics ==========

    async def get_task_stats(
        self, phone_number: str, project_name: Optional[str] = None
    ) -> dict:
        """Get task statistics."""
        return await asyncio.to_thread(
            self._get_task_stats_sync, phone_number, project_name
        )

    def _get_task_stats_sync(
        self, phone_number: str, project_name: Optional[str]
    ) -> dict:
        cursor = self._conn.cursor()

        sql = """
            SELECT
                status,
                COUNT(*) as count
            FROM tasks
            WHERE phone_number = ?
        """
        params: list = [phone_number]

        if project_name:
            sql += " AND project_name = ?"
            params.append(project_name)

        sql += " GROUP BY status"

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        stats = {status.value: 0 for status in TaskStatus}
        for row in rows:
            stats[row["status"]] = row["count"]

        # Get today's completed/failed counts
        cursor.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_today,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_today
            FROM tasks
            WHERE phone_number = ?
            AND completed_at >= date('now')
        """,
            (phone_number,),
        )
        today_row = cursor.fetchone()

        return {
            **stats,
            "total": sum(stats.values()),
            "completed_today": today_row["completed_today"] or 0,
            "failed_today": today_row["failed_today"] or 0,
        }
