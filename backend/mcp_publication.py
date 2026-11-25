"""Visibility for agent-bound MCPs without making private installations public."""
from sqlalchemy import and_, exists, or_

from models import McpDefinition, McpService


def shareable_mcp_definition():
    # Imports deliberately keep scope=user for independent configuration and
    # credentials. Their source controls whether an agent may share them.
    public_source = exists().where(
        McpService.id == McpDefinition.source_mcp_service_id,
        McpService.is_public == True,
        McpService.is_deleted == False,
    ).correlate(McpDefinition)
    return or_(
        and_(McpDefinition.source_mcp_service_id.is_(None),
             McpDefinition.scope.in_(["public", "system"])),
        public_source,
    )
