from typing import Any, Dict, Optional
from pydantic import BaseModel


class GitLabUser(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None


class GitLabProject(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    path_with_namespace: Optional[str] = None


class GitLabObjectAttributes(BaseModel):
    note: Optional[str] = None


class GitLabIssue(BaseModel):
    id: Optional[int] = None
    iid: Optional[int] = None
    title: Optional[str] = None
    web_url: Optional[str] = None


class GitLabEvent(BaseModel):
    object_kind: str
    user: Optional[GitLabUser] = None
    project: Optional[GitLabProject] = None
    object_attributes: Optional[GitLabObjectAttributes] = None
    issue: Optional[GitLabIssue] = None
    raw: Dict[str, Any] = {}

    class Config:
        arbitrary_types_allowed = True
