import json
import logging
import os
from typing import Dict, Optional


class Settings:
    """Application settings loaded from environment variables."""

    # Web server
    host: str = os.getenv("APP_HOST", "0.0.0.0")
    port: int = int(os.getenv("APP_PORT", "8000"))

    # GitLab
    gitlab_webhook_secret: Optional[str] = os.getenv("GITLAB_WEBHOOK_SECRET")

    # Teamwork
    teamwork_base_url: str = os.getenv("TEAMWORK_BASE_URL", "https://yourcompany.teamwork.com")
    teamwork_api_token: Optional[str] = os.getenv("TEAMWORK_API_TOKEN")
    teamwork_user_map_json: Optional[str] = os.getenv("TEAMWORK_USER_MAP_JSON")
    teamwork_project_map_json: Optional[str] = os.getenv("TEAMWORK_PROJECT_MAP_JSON")
    teamwork_dry_run: bool = os.getenv("TEAMWORK_DRY_RUN", "true").lower() in {"1", "true", "yes"}

    def __init__(self) -> None:
        self.teamwork_user_map: Dict[str, str] = {}
        self.teamwork_project_map: Dict[str, str] = {}
        if self.teamwork_user_map_json:
            try:
                self.teamwork_user_map = json.loads(self.teamwork_user_map_json)
            except Exception as exc:
                logging.getLogger(__name__).warning("Invalid TEAMWORK_USER_MAP_JSON: %s", exc)
        if self.teamwork_project_map_json:
            try:
                self.teamwork_project_map = json.loads(self.teamwork_project_map_json)
            except Exception as exc:
                logging.getLogger(__name__).warning("Invalid TEAMWORK_PROJECT_MAP_JSON: %s", exc)


settings = Settings()
