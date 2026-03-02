from typing import Any, Dict, Optional, Tuple

from app.models.event_models import GitLabEvent


def extract_core_info(evt: GitLabEvent) -> Tuple[Optional[int], Optional[str], Optional[int], Optional[str], Optional[str]]:
    """Return (issue_id, issue_title, project_id, project_path, user_name)."""
    issue_id = evt.issue.id if evt.issue and evt.issue.id is not None else None
    issue_title = evt.issue.title if evt.issue else None
    project_id = evt.project.id if evt.project and evt.project.id is not None else None
    project_path = evt.project.path_with_namespace if evt.project else None
    user_name = evt.user.name if evt.user else None
    return issue_id, issue_title, project_id, project_path, user_name


def get_note_text(payload: Dict[str, Any]) -> Optional[str]:
    # GitLab note event usually has object_attributes.note
    try:
        return payload.get("object_attributes", {}).get("note")
    except Exception:
        return None
