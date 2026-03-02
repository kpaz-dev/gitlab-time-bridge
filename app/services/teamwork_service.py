import base64
import logging
from datetime import date as _date
from typing import Optional, Tuple, Union, Dict, Any

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

    async def log_time_minutes(
        self,
        *,
        task_id: str,
        minutes: int,
        description: str,
        date: Optional[Union[str, Dict[str, Any]]] = None,
        is_billable: Optional[bool] = None,
    ) -> bool:
        """Log time in Teamwork against a specific task using minutes.

        Endpoint: POST /projects/api/v3/tasks/{taskId}/time.json
        Body shape (per docs):
        {
          "timelog": {
            "minutes": 120,
            "description": "...",
            "date": "YYYY-MM-DD",
            "isBillable": true
          }
        }
        """
        # Endpoint for task-specific time in Teamwork v3:
        # POST /projects/api/v3/tasks/{taskId}/time.json
        # Body shape:
        # {
        #   "timelog": {
        #     "minutes": 120,
        #     "description": "...",
        #     "date": {"year": 2026, "month": 3, "day": 2},
        #     "isBillable": true
        #   }
        # }
        tl: dict = {
            "minutes": int(minutes),
            "description": description,
        }

        # Compose date as required by Teamwork for this endpoint
        # According to latest info, expected shape is:
        # { "type": "date", "value": "YYYY-MM-DD" }
        def _to_datestr(d: Optional[Union[str, Dict[str, Any]]]) -> str:
            if isinstance(d, str) and len(d) >= 10:
                return d[:10]
            if isinstance(d, dict):
                y = d.get("year")
                m = d.get("month")
                dd = d.get("day")
                if y and m and dd:
                    return f"{int(y):04d}-{int(m):02d}-{int(dd):02d}"
            t = _date.today()
            return f"{t.year:04d}-{t.month:02d}-{t.day:02d}"

        tl["date"] = _to_datestr(date)

        if is_billable is not None:
            tl["isBillable"] = bool(is_billable)
        payload = {"timelog": tl}

        if self.dry_run:
            logger.info(
                "[DRY-RUN] Would send time (minutes) to Teamwork",
                extra={"task_id": task_id, "minutes": minutes, "date": date, "payload": payload},
            )
            return True

        url = f"{self.base_url}/projects/api/v3/tasks/{task_id}/time.json"
        headers = {"Content-Type": "application/json", **self._auth_header()}

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                r = await client.post(url, json=payload, headers=headers)
                if r.status_code in (200, 201):
                    logger.info("Time (minutes) logged in Teamwork", extra={"status": r.status_code})
                    return True
                logger.error(
                    "Failed to log time (minutes) in Teamwork",
                    extra={"status": r.status_code, "body": r.text, "payload": payload},
                )

                logger.info("Failed to log time (minutes) in Teamwork",
                    extra={"status": r.status_code, "body": r.text, "payload": payload})

                logger.info(r.text)

                return False
            except Exception as exc:
                logger.exception("Error calling Teamwork API (minutes): %s", exc)
                return False

    async def _list_tasklist_tasks(self, tasklist_id: str) -> Optional[list[dict]]:
        if self.dry_run:
            logger.info("[DRY-RUN] Would list tasks in tasklist", extra={"tasklist_id": tasklist_id})
            return []
        url = f"{self.base_url}/projects/api/v3/tasklists/{tasklist_id}/tasks.json"
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
        # Optional heuristic: try to match by GitLab web URL or IID marker present in description
        for t in tasks:
            desc = t.get("description") or ""
            if issue_web_url and issue_web_url in desc:
                task_id = str(t.get("id")) if t.get("id") is not None else None
                if task_id:
                    logger.info("Matched Teamwork task by issue URL in description", extra={"task_id": task_id})
                    return True, task_id

        # Create
        body_desc = (description or "").strip()
        if issue_web_url:
            body_desc = f"{body_desc}\n\nGitLab: {issue_web_url}".strip()

        # Build payload dynamically for better API compatibility
        # Según documentación v3: el campo requerido es "name"
        task_obj: dict = {"name": title}
        if body_desc:
            task_obj["description"] = body_desc
        payload = {"task": task_obj}

        if self.dry_run:
            logger.info(
                "[DRY-RUN] Would create task in Teamwork",
                extra={"tasklist_id": tasklist_id, "title": title, "description": body_desc, "payload": payload},
            )
            # Simulate a task id
            return True, "DRYRUN_TASK_ID"

        # Create task under the specific task list
        url = f"{self.base_url}/projects/api/v3/tasklists/{tasklist_id}/tasks.json"
        headers = {"Content-Type": "application/json", **self._auth_header()}
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                r = await client.post(url, json=payload, headers=headers)
                if r.status_code in (200, 201):
                    data = r.json()
                    task_id = str(data.get("task", {}).get("id") or data.get("id")) if isinstance(data, dict) else None
                    logger.info("Created Teamwork task", extra={"task_id": task_id, "status": r.status_code})
                    return True, task_id
                # Log full error body to help diagnose payload/endpoint issues
                logger.error("Failed to create task", extra={"status": r.status_code, "body": r.text})
                return False, None
            except Exception as exc:
                logger.exception("Error creating task: %s", exc)
                return False, None


teamwork_service = TeamworkService()
