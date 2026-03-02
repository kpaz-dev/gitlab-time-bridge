import logging
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.models.event_models import GitLabEvent
from app.parsers.time_parser import parse_time_note
from app.services.gitlab_service import extract_core_info, get_note_text
from app.services.teamwork_service import teamwork_service


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/gitlab")
async def gitlab_webhook(request: Request, x_gitlab_token: str | None = Header(default=None)) -> Dict[str, Any]:
    # Validate secret if configured
    if settings.gitlab_webhook_secret:
        if not x_gitlab_token or x_gitlab_token != settings.gitlab_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook token")

    payload: Dict[str, Any] = await request.json()
    evt = GitLabEvent.parse_obj({**payload, "raw": payload})

    if evt.object_kind != "note":
        logger.debug("Ignoring non-note event", extra={"object_kind": evt.object_kind})
        return {"status": "ignored", "reason": "not a note"}

    note_text = get_note_text(payload)
    seconds = parse_time_note(note_text or "")
    if not seconds:
        logger.debug("No time entry detected in note", extra={"note": note_text})
        return {"status": "ignored", "reason": "no time detected"}

    issue_id, issue_title, project_id, project_path, user_name = extract_core_info(evt)

    # Map GitLab project to Teamwork project
    tw_project_id = None
    if project_id is not None and str(project_id) in settings.teamwork_project_map:
        tw_project_id = settings.teamwork_project_map[str(project_id)]
    elif project_path and project_path in settings.teamwork_project_map:
        tw_project_id = settings.teamwork_project_map[project_path]
    else:
        # Fallback to default project if provided under key "default"
        tw_project_id = settings.teamwork_project_map.get("default")

    # Map user name/username to Teamwork user id if provided (optional)
    tw_user_id = None
    if evt.user:
        for key in filter(None, [str(evt.user.id) if evt.user.id is not None else None, evt.user.username, evt.user.name]):
            if key in settings.teamwork_user_map:
                tw_user_id = settings.teamwork_user_map[key]
                break

    description = f"GitLab #{issue_id}: {issue_title} — {user_name or 'unknown'}"

    ok = await teamwork_service.log_time(
        project_id=str(tw_project_id) if tw_project_id else "",
        description=description,
        user_id=str(tw_user_id) if tw_user_id else None,
        seconds=seconds,
        issue_id=issue_id,
        issue_title=issue_title,
    )

    if not ok:
        raise HTTPException(status_code=502, detail="Failed to log time in Teamwork")

    return {
        "status": "ok",
        "seconds": seconds,
        "issue_id": issue_id,
        "issue_title": issue_title,
        "project": project_path or project_id,
    }
