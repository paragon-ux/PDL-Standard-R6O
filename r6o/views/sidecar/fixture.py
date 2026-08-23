from __future__ import annotations

"""Reference-sized presentation data for H2-C visual qualification."""

CANONICAL_ACTIONS = (
    {"action_id": "confirm_prompt", "label": "Confirm this prompt", "ordinal": 1, "enabled": True},
    {"action_id": "change_task", "label": "Change the task", "ordinal": 2, "enabled": True},
    {"action_id": "change_approach", "label": "Change the approach", "ordinal": 3, "enabled": True},
    {"action_id": "something_else", "label": "Something else...", "ordinal": 4, "enabled": True},
)

CANONICAL_ARTIFACT_BODY = """# Prompt

Build a task manager with:
- User authentication
- Project management
- Task tracking
- Due dates and reminders

Target tech stack: React + FastAPI + SQLite"""
