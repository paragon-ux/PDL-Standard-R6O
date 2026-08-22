from __future__ import annotations

from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.model_binding.memory_model import StaticModelPort
from r6o.presentation_transport import PresentationAdapter
from r6o.tests.helpers import artifact, state
from r6o.views.tui import TuiController
from r6o.views.tui.controller import _display_width
from r6o.views.tui.app import TuiApplication

G06_ACTIVATION = "Use $confirm-with-pseudocode to explain the difference between optimistic and pessimistic locking for senior developers."
G06_PROMPT = "Explain the difference between optimistic locking and pessimistic locking for an audience of senior developers."
G06_PLAN = (
    "IDENTIFY the target audience as senior developers\n"
    "INTRODUCE the subject of concurrency control\n"
    "DEFINE optimistic locking\n"
    "DEFINE pessimistic locking\n"
    "COMPARE the two approaches\n"
    "SUMMARIZE the differences"
)
A02_ACTIVATION = "Use $confirm-with-pseudocode to compare Kafka and RabbitMQ for event delivery."
A02_REVISION = "This is not confirmed. The audience should be data engineers, not backend engineers."
A02_PROMPT = "COMPARE Kafka and RabbitMQ for event delivery, intended for data engineers."


def _static_tui() -> TuiController:
    return TuiController(
        PresentationAdapter(StaticModelPort(state(), {"prompt:P1": artifact()})),
        "I-1",
    )


def test_tui_renders_responsive_persistent_layouts() -> None:
    tui = _static_tui()
    wide = tui.render(100, 28)
    narrow = tui.render(56, 28)
    assert "Authoritative Artifact" in wide and "Review Options" in wide
    assert "Review >" in wide and "Confirm prompt" in wide
    assert "Authoritative Artifact" in narrow and "Review Options" in narrow
    assert len(wide.splitlines()) <= 28
    assert len(narrow.splitlines()) <= 28


def test_tui_never_exceeds_supported_viewport_widths() -> None:
    tui = _static_tui()
    for width in (42, 56, 76, 100, 120):
        assert all(
            _display_width(line) <= width
            for line in tui.render(width, 30).splitlines()
        )


def test_minimum_viewport_keeps_every_action_keyboard_reachable_and_cued() -> None:
    tui = _static_tui()
    labels = [item["label"] for item in tui.state.actions]
    observed = []
    for _ in labels:
        screen = tui.render(42, 14)
        observed.append(labels[tui.action_index])
        assert labels[tui.action_index] in screen
        tui.handle_key("DOWN")
    assert observed == labels
    assert "↓" in _static_tui().render(42, 14)


def test_tui_keyboard_focus_editing_scroll_and_view_only_close() -> None:
    tui = _static_tui()
    tui.handle_key("DOWN")
    tui.handle_key("DOWN")
    tui.handle_key("DOWN")
    result = tui.handle_key("ENTER")
    assert result["result_type"] == "FOCUS_REQUIRED"
    assert tui.focus == "input"
    for value in "Revise this":
        tui.handle_key(value)
    tui.handle_key("LEFT")
    tui.handle_key("BACKSPACE")
    assert tui.input_buffer == "Revise ths"
    tui.handle_key("TAB")
    assert tui.focus == "artifact"
    tui.handle_key("PAGE_DOWN")
    assert tui.artifact_scroll > 0
    tui.handle_key("CTRL_Q")
    assert tui.closed


def test_tui_application_uses_persistent_driver_event_loop() -> None:
    class FakeDriver:
        def __init__(self) -> None:
            self.keys = iter([None, "TAB", "CTRL_Q"])
            self.screens: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def size(self):
            return (88, 24)

        def draw(self, screen):
            self.screens.append(screen)

        def read_key(self, _timeout):
            return next(self.keys)

    tui = _static_tui()
    driver = FakeDriver()
    TuiApplication(tui, driver).run()
    assert tui.closed
    assert len(driver.screens) >= 2
    assert all("Review >" in screen for screen in driver.screens)


def test_g06_real_tui_key_path_has_no_duplicate_activation(
    tmp_path, baseline_repo, recorded_worker_factory
) -> None:
    binding = LocalRuntimeModelBinding(
        baseline_repo,
        worker=recorded_worker_factory(["G06"]),
        workspace_root=tmp_path / "g06-tui",
    )
    started = binding.start_or_resume(
        ModelSessionRequest(request_id="g06-tui", task_text=G06_ACTIVATION)
    )
    tui = TuiController(PresentationAdapter(binding), started.session_id)
    stages = [tui.projection["stage"]]
    assert tui.handle_key("ENTER")["result_type"] == "REVISION"
    stages.append(tui.projection["stage"])
    assert tui.handle_key("ENTER")["result_type"] == "REVISION"
    stages.append(tui.projection["stage"])
    assert stages == ["PROMPT_REVIEW", "PLAN_REVIEW", "CLOSED_SUCCESS"]
    assert tui.closed
    assert binding.read_artifact(tui.state.session_id, "prompt:current").body == G06_PROMPT
    assert binding.read_artifact(tui.state.session_id, "plan:current").body == G06_PLAN
    binding.close()


def test_a02_real_tui_editable_input_path_has_no_duplicate_activation(
    tmp_path, baseline_repo, recorded_worker_factory
) -> None:
    binding = LocalRuntimeModelBinding(
        baseline_repo,
        worker=recorded_worker_factory(["A02"]),
        workspace_root=tmp_path / "a02-tui",
    )
    started = binding.start_or_resume(
        ModelSessionRequest(request_id="a02-tui", task_text=A02_ACTIVATION)
    )
    tui = TuiController(PresentationAdapter(binding), started.session_id)
    tui.state.qualification_case = "A02"
    tui.prefill_input(A02_REVISION)
    assert tui.input_buffer == A02_REVISION
    assert "preloaded" in tui.notice
    tui.select_action(3)
    assert tui.focus == "input"
    result = tui.handle_key("ENTER")
    assert result["result_type"] == "REVISION"
    assert tui.projection["stage"] == "PROMPT_REVIEW"
    assert tui.focus == "actions"
    assert binding.read_artifact(tui.state.session_id, "prompt:current").body == A02_PROMPT
    binding.close()


def test_stale_text_refresh_to_real_terminal_projection_exits_tui(
    tmp_path, baseline_repo, recorded_worker_factory
) -> None:
    binding = LocalRuntimeModelBinding(
        baseline_repo,
        worker=recorded_worker_factory(["G06"]),
        workspace_root=tmp_path / "g06-stale-terminal-tui",
    )
    started = binding.start_or_resume(
        ModelSessionRequest(request_id="g06-stale-tui", task_text=G06_ACTIVATION)
    )
    adapter = PresentationAdapter(binding)
    stale_tui = TuiController(adapter, started.session_id)
    current_tui = TuiController(adapter, started.session_id)
    assert current_tui.select_action()["projection"]["stage"] == "PLAN_REVIEW"
    assert current_tui.select_action()["projection"]["stage"] == "CLOSED_SUCCESS"

    stale_tui.focus = "input"
    stale_tui.input_buffer = "stale feedback"
    stale_tui.cursor = len(stale_tui.input_buffer)
    result = stale_tui.submit_input()
    assert result["result_type"] == "STALE_PROJECTION"
    assert stale_tui.projection["stage"] == "CLOSED_SUCCESS"
    assert stale_tui.closed
    binding.close()


def test_stale_text_refresh_clamps_action_index_to_replacement_projection() -> None:
    initial = PresentationAdapter(
        StaticModelPort(state(), {"prompt:P1": artifact()})
    ).current_projection("I-1")
    replacement = dict(initial)
    replacement["model_revision"] = "model-rev-2"
    replacement["actions"] = replacement["actions"][:1]

    class StaleAdapter:
        def current_projection(self, _session_id):
            return initial

        def submit_input(self, _envelope):
            return {
                "result_type": "STALE_PROJECTION",
                "projection": replacement,
                "error": None,
            }

    tui = TuiController(StaleAdapter(), "I-1")
    tui.action_index = len(tui.state.actions) - 1
    tui.input_buffer = "stale feedback"
    result = tui.submit_input()
    assert result["result_type"] == "STALE_PROJECTION"
    assert tui.action_index == 0
    assert tui.state.actions[0]["action_id"] == "confirm_prompt"
