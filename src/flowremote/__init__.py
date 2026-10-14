"""FlowRemote - mobile supervision and approval for AI-assisted data processing.

Package layout mirrors the layered architecture:

    contracts/      the interface: models, enums, events
    control_plane/  task state machine, review tally, approval, activity log
    agent/          the AI step: explain an exception, suggest a correction
    rpa/            validation engine and execution engine
    connectors/     adapters for the outside systems (OA, BI, workspace)
    api/            HTTP surface
    ui/             browser interface
    devtools/       seed data and local helpers
"""

__all__: list[str] = []
