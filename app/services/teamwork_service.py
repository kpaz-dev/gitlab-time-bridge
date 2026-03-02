import base64
import logging
from typing import Optional

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
        project_id: str,
        description: str,
        user_id: Optional[str],
        seconds: int,
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


teamwork_service = TeamworkService()
