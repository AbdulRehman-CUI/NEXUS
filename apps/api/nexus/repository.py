from fastapi import HTTPException
from sqlalchemy import select

from .database import Workspace


class Repository:
    """Central scoped lookup. Resource IDs never substitute for workspace authorization."""

    def __init__(self, sessions, settings):
        self.sessions = sessions
        self.settings = settings

    def workspace(self, session, workspace_id):
        from .auth import authorize

        authorize(self.settings, session, workspace_id)
        workspace = session.get(Workspace, workspace_id)
        if workspace is None:
            raise HTTPException(404, "Workspace not found")
        return workspace

    def get(self, session, model, resource_id, workspace_id):
        self.workspace(session, workspace_id)
        resource = session.scalar(
            select(model).where(model.id == resource_id, model.workspace_id == workspace_id)
        )
        if resource is None:
            raise HTTPException(404, "Resource not found in this workspace")
        return resource
