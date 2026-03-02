import base64
import logging
from typing import Optional, Tuple

import httpx

from app.config import settings


logger = logging.getLogger(__name__)


class TeamworkService:
    def __init__(self) -> None:
        self.base_url = settings.teamwork_base_url.rstrip("/")
        self.api_token = settings.teamwork_api_token
        self.dry_run = settings.teamwork_dry_run or not self.api_token

    def _auth_header(self) -> dict:
        if not self.api_token:
            return {}
        # Teamwork uses Basic auth with token as username and 'x' as password
        token = f"{self.api_token}:x".encode()
        b64 = base64.b64encode(token).decode()
        return {"Authorization": f"Basic {b64}"}

    async def log_time(
        self,
        project_id: str | None,
        description: str,
        user_id: Optional[str],
        seconds: int,
        task_id: Optional[str] = None,
        issue_id: Optional[int] = None,
        issue_title: Optional[str] = None,
    ) -> bool:
        """Send time entry to Teamwork.

        This uses Teamwork v3 time API shape approximately. In dry-run, only logs.
        """
        payload = {
            "timeLog": {
                "description": description,
                "seconds": seconds,
                "userId": user_id,
                "projectId": project_id,
                "taskId": task_id,
                "tags": ["gitlab-sync"],
                "externalRef": {
                    "service": "gitlab",
                    "id": str(issue_id) if issue_id else None,
                    "title": issue_title,
                },
            }
        }

        if self.dry_run:
            logger.info(
                "[DRY-RUN] Would send time to Teamwork",
                extra={
                    "project_id": project_id,
                    "task_id": task_id,
                    "user_id": user_id,
                    "seconds": seconds,
                    "issue_id": issue_id,
                    "issue_title": issue_title,
                    "payload": payload,
                },
            )
            return True

        url = f"{self.base_url}/projects/api/v3/time.json"
        headers = {"Content-Type": "application/json", **self._auth_header()}

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                r = await client.post(url, json=payload, headers=headers)
                if r.status_code in (200, 201):
                    logger.info("Time logged in Teamwork", extra={"status": r.status_code})
                    return True
                logger.error(
                    "Failed to log time in Teamwork",
                    extra={"status": r.status_code, "body": r.text},
                )
                return False
            except Exception as exc:
                logger.exception("Error calling Teamwork API: %s", exc)
                return False

    async def _list_tasklist_tasks(self, tasklist_id: str) -> Optional[list[dict]]:
        if self.dry_run:
            logger.info("[DRY-RUN] Would list tasks in tasklist", extra={"tasklist_id": tasklist_id})
            return []
        url = f"{self.base_url}/projects/api/v3/tasklists/{tasklist_id}/tasks.json"
        print("si llegó hasta aquí")
        headers = self._auth_header()
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                r = await client.get(url, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    # Assuming response contains key 'tasks'
                    return data.get("tasks") or []
                logger.error("Failed to list tasks", extra={"status": r.status_code, "body": r.text})
                return None
            except Exception as exc:
                logger.exception("Error listing tasks: %s", exc)
                return None

    async def create_or_find_task(
        self,
        tasklist_id: str,
        title: str,
        description: Optional[str] = None,
        issue_web_url: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Find a task by exact title in the task list; if not found, create it.

        Returns tuple (ok, task_id)
        """
        # Try find existing by exact title
        tasks = await self._list_tasklist_tasks(tasklist_id)
        if tasks is None:
            # couldn't list; continue to try create
            tasks = []
        for t in tasks:
            t_title = t.get("title") or t.get("name") or t.get("content")
            if t_title and t_title == title:
                task_id = str(t.get("id")) if t.get("id") is not None else None
                if task_id:
                    logger.info("Found existing Teamwork task", extra={"task_id": task_id, "title": title})
                    return True, task_id

        # Create
        body_desc = description or ""
        if issue_web_url:
            body_desc = f"{body_desc}\n\nGitLab: {issue_web_url}".strip()

        payload = {
            "task": {
                "taskListId": tasklist_id,
                "title": title,
                "description": body_desc,
            }
        }

        if self.dry_run:
            logger.info(
                "[DRY-RUN] Would create task in Teamwork",
                extra={"tasklist_id": tasklist_id, "title": title, "description": body_desc, "payload": payload},
            )
            # Simulate a task id
            return True, "DRYRUN_TASK_ID"

        url = f"{self.base_url}/projects/api/v3/tasks.json"
        headers = {"Content-Type": "application/json", **self._auth_header()}
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                r = await client.post(url, json=payload, headers=headers)
                if r.status_code in (200, 201):
                    data = r.json()
                    task_id = str(data.get("task", {}).get("id") or data.get("id")) if isinstance(data, dict) else None
                    logger.info("Created Teamwork task", extra={"task_id": task_id, "status": r.status_code})
                    return True, task_id
                logger.error("Failed to create task", extra={"status": r.status_code, "body": r.text})
                return False, None
            except Exception as exc:
                logger.exception("Error creating task: %s", exc)
                return False, None


teamwork_service = TeamworkService()
