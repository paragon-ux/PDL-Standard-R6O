from __future__ import annotations

from r6o.model_binding.memory_model import InMemoryModel
from r6o.viewmodel.dispatcher import handle_input, validate_command_result
from r6o.viewmodel.projection import build_focus_projection_from_port


def _envelope(port: InMemoryModel, **overrides):
    projection = build_focus_projection_from_port(port, port._session_id)
    base = {
        "schema_version": "r6o-input-envelope-1",
        "session_id": port._session_id,
        "source": "STRUCTURED_ACTION",
        "model_revision": projection["model_revision"],
        "text": None,
        "action_id": "confirm_prompt",
        "projection_id": projection["projection_id"],
    }
    base.update(overrides)
    return base


def test_stale_projection_fails_closed() -> None:
    port = InMemoryModel()
    before = port.read_state(port._session_id)
    result = handle_input(_envelope(port, model_revision="obsolete"), port)
    validate_command_result(result)
    assert result["result_type"] == "STALE_PROJECTION"
    assert result["ok"] is False
    after = port.read_state(port._session_id)
    assert after.revision == before.revision  # no mutation


def test_unknown_action_fails_closed() -> None:
    port = InMemoryModel()
    result = handle_input(_envelope(port, action_id="does_not_exist"), port)
    assert result["result_type"] == "ERROR"
    assert result["error"]["code"] == "UNKNOWN_ACTION"


def test_invalid_envelope_rejected() -> None:
    port = InMemoryModel()
    result = handle_input({"source": "STRUCTURED_ACTION"}, port)
    assert result["result_type"] == "ERROR"
    assert result["error"]["code"] == "INVALID_ENVELOPE"
