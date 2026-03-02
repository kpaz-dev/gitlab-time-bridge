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
    logger.info("Received GitLab webhook")
    # Validate secret if configured
    if settings.gitlab_webhook_secret:
        if not x_gitlab_token or x_gitlab_token != settings.gitlab_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook token")

    payload: Dict[str, Any] = await request.json()
    evt = GitLabEvent.parse_obj({**payload, "raw": payload})

    # Handle Issue events: create/link task in Teamwork Task List
    if evt.object_kind == "issue":
        attrs = (payload.get("object_attributes", {}) or {})
        action = attrs.get("action")
        # Process on create/open (and optionally on reopen)
        logger.info("Evento de issue recibido", extra={"action": action})
        if action in {"open", "opened", "reopen", "reopened"} or action is None:
            logger.info("Procesando creación/apertura de issue")
            # En eventos de tipo issue, los datos vienen en object_attributes
            iid = attrs.get("iid")
            title = attrs.get("title") or "(sin título)"
            task_title = f"[GL#{iid}] {title}" if iid is not None else title
            issue_desc = attrs.get("description")
            issue_url = attrs.get("url") or attrs.get("web_url")

            if not settings.teamwork_tasklist_id:
                logger.warning("TEAMWORK_TASKLIST_ID not set; cannot create Teamwork Task for issue")
                return {"status": "ignored", "reason": "no tasklist configured"}

            ok, task_id = await teamwork_service.create_or_find_task(
                tasklist_id=settings.teamwork_tasklist_id,
                title=task_title,
                description=issue_desc,
                issue_web_url=issue_url,
            )
            if not ok:
                raise HTTPException(status_code=502, detail="Failed to create/find Teamwork task")
            return {"status": "ok", "task_id": task_id, "task_title": task_title}

        return {"status": "ignored", "reason": f"issue action {action} not handled"}

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

    # If a task list is configured, try to log time against the corresponding task
    task_id_to_use = None
    if settings.teamwork_tasklist_id:
        # Build deterministic task title from issue iid + title
        iid = evt.issue.iid if evt.issue else None
        base_title = issue_title or "(sin título)"
        task_title = f"[GL#{iid}] {base_title}" if iid is not None else base_title
        ok_find, found_task_id = await teamwork_service.create_or_find_task(
            tasklist_id=settings.teamwork_tasklist_id,
            title=task_title,
            description=(evt.raw.get("object_attributes", {}) or {}).get("description") if settings.teamwork_create_task_on_note else None,
            issue_web_url=evt.issue.web_url if evt.issue else None,
        )
        if ok_find:
            task_id_to_use = found_task_id
        else:
            # if cannot find/create, we will fallback to project level
            logger.warning("Could not find/create Teamwork task for note; will fallback to project-level time")

    ok = await teamwork_service.log_time(
        project_id=(str(tw_project_id) if tw_project_id else None) if not task_id_to_use else None,
        description=description,
        user_id=str(tw_user_id) if tw_user_id else None,
        seconds=seconds,
        task_id=task_id_to_use,
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
