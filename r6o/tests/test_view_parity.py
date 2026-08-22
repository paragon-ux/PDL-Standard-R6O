from __future__ import annotations

import sys
from pathlib import Path

from r6o.model_binding.base import ModelSessionRequest
from r6o.model_binding.local_runtime import LocalRuntimeModelBinding
from r6o.model_binding.memory_model import StaticModelPort
from r6o.presentation_transport import PresentationAdapter
from r6o.tests.helpers import artifact, state
from r6o.views.sidecar.model import SidecarModel
from r6o.views.tui.controller import TuiController

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


def test_tui_and_sidecar_share_projection_semantics() -> None:
    port = StaticModelPort(state(), {"prompt:P1": artifact()})
    adapter = PresentationAdapter(port)
    tui = TuiController(adapter, "I-1")
    side = SidecarModel(adapter, "I-1")
    tui_actions = [(a["ordinal"], a["action_id"], a["label"]) for a in tui.projection["actions"]]
    side_actions = [(a["ordinal"], a["action_id"], a["label"]) for a in side.projection["actions"]]
    assert tui_actions == side_actions
    assert [a[0] for a in tui_actions] == [1, 2, 3, 4]
    assert {a[1] for a in tui_actions} == {"confirm_prompt", "change_task", "change_approach", "something_else"}


def _binding(tmp_path, baseline_repo, recorded_worker_factory, case_ids):
    worker = recorded_worker_factory(case_ids)
    return LocalRuntimeModelBinding(baseline_repo, worker=worker, workspace_root=tmp_path / "ws", run_id="parity")


def test_g06_tui_structured_parity(tmp_path, baseline_repo, recorded_worker_factory):
    sys.path.insert(0, str(baseline_repo))
    from host.app import PDLtHost

    binding = _binding(tmp_path, baseline_repo, recorded_worker_factory, ["G06"])
    snapshot = binding.start_or_resume(ModelSessionRequest(request_id="g06", task_text=G06_ACTIVATION))
    session = snapshot.session_id
    adapter = PresentationAdapter(binding)
    tui = TuiController(adapter, session)
    tui.submit_text(G06_ACTIVATION)
    assert tui.select_action(1)["result_type"] == "REVISION"
    assert tui.select_action(1)["result_type"] == "REVISION"
    prompt = binding.read_artifact(session, "prompt:current")
    plan = binding.read_artifact(session, "plan:current")
    stage = binding.read_state(session).stage
    binding.close()

    worker2 = recorded_worker_factory(["G06"])
    host = PDLtHost(baseline_repo, worker=worker2, workspace_root=tmp_path / "direct", run_id="direct").start()
    try:
        for turn in [G06_ACTIVATION, "Yes, that is what I mean.", "Confirm the plan and execute."]:
            host.handle(turn)
        workspace = Path(host.status()["workspace_path"])
        direct_prompt = (workspace / "stages" / "10_prompt" / "output" / "current.md").read_text(encoding="utf-8").rstrip("\n")
        direct_plan = (workspace / "stages" / "30_plan" / "output" / "current.md").read_text(encoding="utf-8").rstrip("\n")
        direct_stage = host.status()["controller_state"]["stage"]
    finally:
        host.close()

    assert stage == direct_stage == "CLOSED_SUCCESS"
    assert prompt.body == direct_prompt == G06_PROMPT
    assert plan.body == direct_plan == G06_PLAN


def test_a02_free_response_parity(tmp_path, baseline_repo, recorded_worker_factory):
    sys.path.insert(0, str(baseline_repo))
    from host.app import PDLtHost

    binding = _binding(tmp_path, baseline_repo, recorded_worker_factory, ["A02"])
    snapshot = binding.start_or_resume(ModelSessionRequest(request_id="a02", task_text=A02_ACTIVATION))
    session = snapshot.session_id
    adapter = PresentationAdapter(binding)
    side = SidecarModel(adapter, session)
    side.host_composer_text(A02_ACTIVATION)
    tui = TuiController(adapter, session)
    tui.submit_text(A02_REVISION)
    prompt = binding.read_artifact(session, "prompt:current")
    stage = binding.read_state(session).stage
    binding.close()

    worker2 = recorded_worker_factory(["A02"])
    host = PDLtHost(baseline_repo, worker=worker2, workspace_root=tmp_path / "direct2", run_id="direct2").start()
    try:
        host.handle(A02_ACTIVATION)
        host.handle(A02_REVISION)
        workspace = Path(host.status()["workspace_path"])
        direct_prompt = (workspace / "stages" / "10_prompt" / "output" / "current.md").read_text(encoding="utf-8").rstrip("\n")
        direct_stage = host.status()["controller_state"]["stage"]
    finally:
        host.close()

    assert stage == direct_stage == "PROMPT_REVIEW"
    assert prompt.body == direct_prompt == A02_PROMPT



def test_g06_sidecar_structured_parity(tmp_path, baseline_repo, recorded_worker_factory):
    sys.path.insert(0, str(baseline_repo))
    from host.app import PDLtHost

    binding = _binding(tmp_path, baseline_repo, recorded_worker_factory, ["G06"])
    snapshot = binding.start_or_resume(ModelSessionRequest(request_id="g06s", task_text=G06_ACTIVATION))
    session = snapshot.session_id
    adapter = PresentationAdapter(binding)
    side = SidecarModel(adapter, session)
    side.host_composer_text(G06_ACTIVATION)
    assert side.select_action("confirm_prompt")["result_type"] == "REVISION"
    assert side.select_action("confirm_plan")["result_type"] == "REVISION"
    prompt = binding.read_artifact(session, "prompt:current")
    plan = binding.read_artifact(session, "plan:current")
    stage = binding.read_state(session).stage
    binding.close()

    worker2 = recorded_worker_factory(["G06"])
    host = PDLtHost(baseline_repo, worker=worker2, workspace_root=tmp_path / "directs", run_id="directs").start()
    try:
        for turn in [G06_ACTIVATION, "Yes, that is what I mean.", "Confirm the plan and execute."]:
            host.handle(turn)
        workspace = Path(host.status()["workspace_path"])
        direct_prompt = (workspace / "stages" / "10_prompt" / "output" / "current.md").read_text(encoding="utf-8").rstrip("\n")
        direct_plan = (workspace / "stages" / "30_plan" / "output" / "current.md").read_text(encoding="utf-8").rstrip("\n")
        direct_stage = host.status()["controller_state"]["stage"]
    finally:
        host.close()

    assert stage == direct_stage == "CLOSED_SUCCESS"
    assert prompt.body == direct_prompt == G06_PROMPT
    assert plan.body == direct_plan == G06_PLAN


