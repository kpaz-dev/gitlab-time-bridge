import logging
import math
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

        # Optional: handle updates to time tracking when using GitLab native time (no note)
        if action == "update":
            # When time is logged via GitLab sidebar, total_time_spent changes.
            changes = (payload.get("changes", {}) or {})
            tts_change = changes.get("total_time_spent") or changes.get("time_spent", {})
            # GitLab usually provides { previous: int|null, current: int }
            prev_val = None
            curr_val = None
            if isinstance(tts_change, dict):
                prev_val = tts_change.get("previous")
                curr_val = tts_change.get("current")
            # Fallback: read from object_attributes
            if curr_val is None:
                curr_val = attrs.get("total_time_spent")
            # Compute delta in seconds
            try:
                prev_s = int(prev_val) if prev_val is not None else 0
                curr_s = int(curr_val) if curr_val is not None else 0
            except Exception:
                prev_s, curr_s = 0, 0
            delta_s = max(0, curr_s - prev_s)
            if delta_s <= 0:
                logger.info("Issue update without positive time delta", extra={"delta_seconds": delta_s})
                return {"status": "ignored", "reason": "no positive time delta"}

            # Build deterministic title and description
            iid = attrs.get("iid")
            title = attrs.get("title") or "(sin título)"
            task_title = f"[GL#{iid}] {title}" if iid is not None else title
            issue_url = attrs.get("url") or attrs.get("web_url")
            user_name = evt.user.name if evt.user and evt.user.name else None
            description = f"GitLab #{attrs.get('id') or iid}: {title} — {user_name or 'unknown'}"

            # If we have task list configured, prefer task-level logging
            if settings.teamwork_tasklist_id:
                ok_find, found_task_id = await teamwork_service.create_or_find_task(
                    tasklist_id=settings.teamwork_tasklist_id,
                    title=task_title,
                    description=None,  # no need to update description on update
                    issue_web_url=issue_url,
                )
                if ok_find and found_task_id:
                    minutes = max(1, math.ceil(delta_s / 60))
                    ok_time = await teamwork_service.log_time_minutes(
                        task_id=found_task_id,
                        minutes=minutes,
                        description=description,
                    )
                    if not ok_time:
                        raise HTTPException(status_code=502, detail="Failed to log time in Teamwork (issue update)")
                    return {
                        "status": "ok",
                        "seconds": delta_s,
                        "minutes": minutes,
                        "task_id": found_task_id,
                        "task_title": task_title,
                    }
                # If cannot find/create, fall back to project level

            # Project-level fallback
            # Map GitLab project to Teamwork project
            project = (payload.get("project", {}) or {})
            project_id = project.get("id")
            project_path = project.get("path_with_namespace")
            tw_project_id = None
            if project_id is not None and str(project_id) in settings.teamwork_project_map:
                tw_project_id = settings.teamwork_project_map[str(project_id)]
            elif project_path and project_path in settings.teamwork_project_map:
                tw_project_id = settings.teamwork_project_map[project_path]
            else:
                tw_project_id = settings.teamwork_project_map.get("default")

            ok_time = await teamwork_service.log_time(
                project_id=str(tw_project_id) if tw_project_id else None,
                description=description,
                user_id=None,
                seconds=delta_s,
                task_id=None,
                issue_id=attrs.get("id"),
                issue_title=title,
            )
            if not ok_time:
                raise HTTPException(status_code=502, detail="Failed to log time in Teamwork (project fallback)")
            return {"status": "ok", "seconds": delta_s, "project": project_path or project_id}

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

    # Prefer logging to a specific Teamwork task if available; otherwise fallback to project-level seconds API
    if task_id_to_use:
        minutes = max(1, math.ceil(seconds / 60))
        # Try to pass the note creation date if available (YYYY-MM-DD)
        note_attrs = (payload.get("object_attributes", {}) or {})
        created_at = note_attrs.get("created_at") or note_attrs.get("updated_at")
        date_str = None
        if isinstance(created_at, str) and len(created_at) >= 10:
            # created_at like "2026-03-02 14:11:01 UTC" → "2026-03-02"
            date_str = created_at.split(" ")[0]
        ok = await teamwork_service.log_time_minutes(
            task_id=task_id_to_use,
            minutes=minutes,
            description=description,
            date=date_str,
        )
    else:
        ok = await teamwork_service.log_time(
            project_id=(str(tw_project_id) if tw_project_id else None),
            description=description,
            user_id=str(tw_user_id) if tw_user_id else None,
            seconds=seconds,
            task_id=None,
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
