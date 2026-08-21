from __future__ import annotations

"""Non-path in-memory Model Port and artifact provider.

Test double proving the ViewModel does not depend on filesystem paths or a
concrete runtime. It is not a second protocol authority.
"""

import hashlib
import json
import uuid
from typing import Any

from r6o.model_binding.base import (
    ArtifactSnapshot,
    ModelRevision,
    SessionInvocation,
    StaleProjectionError,
)

PROMPT_CONFIRM = "Yes, that is what I mean."
PLAN_CONFIRM = "Confirm the plan and execute."


class InMemoryArtifactProvider:
    """Opaque artifact store keyed by reference; no paths."""

    def __init__(self) -> None:
        self._store: dict[str, ArtifactSnapshot] = {}

    def put(self, snapshot: ArtifactSnapshot) -> None:
        self._store[snapshot.artifact_ref] = snapshot

    def read(self, artifact_ref: str) -> ArtifactSnapshot:
        try:
            return self._store[artifact_ref]
        except KeyError:
            raise KeyError(f"unknown artifact ref: {artifact_ref}") from None


class InMemoryModel:
    """Scripted Model Port used for ViewModel/artifact-provider tests."""

    port_version = "r6o-model-port-1"

    def __init__(self, artifacts: InMemoryArtifactProvider | None = None) -> None:
        self.artifacts = artifacts or InMemoryArtifactProvider()
        self._state: dict[str, Any] = {
            "stage": "PROMPT_REVIEW",
            "prompt_revision": "P0",
            "plan_revision": None,
            "prompt_confirmed": False,
            "plan_confirmed": False,
            "result": None,
        }
        self._session_id = f"mem-{uuid.uuid4().hex[:8]}"
        self._seed_prompt()

    def _seed_prompt(self) -> None:
        body = "COMPARE Kafka and RabbitMQ for event delivery."
        self.artifacts.put(
            ArtifactSnapshot(
                artifact_ref="prompt:P0",
                artifact_revision="P0",
                artifact_kind="prompt",
                title="Authoritative Prompt (PDL.md)",
                body=body,
                capabilities={"copy": True, "open_external": False},
            )
        )

    def _revision(self) -> ModelRevision:
        canonical = json.dumps(self._state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        token = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return ModelRevision(self._session_id, token, str(self._state["stage"]), dict(self._state))

    def start_or_resume(self, invocation: SessionInvocation) -> ModelRevision:
        return self._revision()

    def read_state(self, session_id: str) -> ModelRevision:
        if session_id != self._session_id:
            raise KeyError(f"unknown session: {session_id}")
        return self._revision()

    def read_artifact(self, session_id: str, artifact_ref: str, expected_revision: str | None = None) -> ArtifactSnapshot:
        self.read_state(session_id)
        if artifact_ref.endswith(":current"):
            kind = artifact_ref.split(":", 1)[0]
            revision_key = f"{kind}_revision"
            current_rev = self._state.get(revision_key)
            if not current_rev:
                raise KeyError(f"no current {kind} artifact")
            artifact_ref = f"{kind}:{current_rev}"
        snapshot = self.artifacts.read(artifact_ref)
        if expected_revision is not None and expected_revision != snapshot.artifact_revision:
            raise StaleProjectionError(f"artifact revision {expected_revision} != {snapshot.artifact_revision}")
        return snapshot

    def submit_user_message(self, session_id: str, text: str, expected_revision: str | None) -> ModelRevision:
        current = self.read_state(session_id)
        if expected_revision is not None and expected_revision != current.revision:
            raise StaleProjectionError(f"revision {expected_revision} != {current.revision}")
        stage = self._state["stage"]
        if text == PROMPT_CONFIRM and stage == "PROMPT_REVIEW":
            self._state["prompt_confirmed"] = True
            self._state["stage"] = "PLAN_REVIEW"
            self._state["plan_revision"] = "R1"
            self.artifacts.put(
                ArtifactSnapshot(
                    artifact_ref="plan:R1",
                    artifact_revision="R1",
                    artifact_kind="plan",
                    title="Authoritative Response Plan (PDL.md)",
                    body="IDENTIFY the target audience\nDEFINE the comparison\nSUMMARIZE the differences",
                    capabilities={"copy": True, "open_external": False},
                )
            )
        elif text == PLAN_CONFIRM and stage == "PLAN_REVIEW":
            self._state["plan_confirmed"] = True
            self._state["stage"] = "EXECUTION_READY"
            self._state["result"] = "Deterministic in-memory result."
            self._state["stage"] = "CLOSED_SUCCESS"
        elif stage in ("PROMPT_REVIEW", "PLAN_REVIEW"):
            if stage == "PROMPT_REVIEW":
                self._state["prompt_revision"] = f"P{int(self._state['prompt_revision'][1:]) + 1}"
                self.artifacts.put(
                    ArtifactSnapshot(
                        artifact_ref=f"prompt:{self._state['prompt_revision']}",
                        artifact_revision=self._state["prompt_revision"],
                        artifact_kind="prompt",
                        title="Authoritative Prompt (PDL.md)",
                        body=text,
                        capabilities={"copy": True, "open_external": False},
                    )
                )
            else:
                self._state["plan_revision"] = f"R{int(self._state['plan_revision'][1:]) + 1}"
                self.artifacts.put(
                    ArtifactSnapshot(
                        artifact_ref=f"plan:{self._state['plan_revision']}",
                        artifact_revision=self._state["plan_revision"],
                        artifact_kind="plan",
                        title="Authoritative Response Plan (PDL.md)",
                        body=text,
                        capabilities={"copy": True, "open_external": False},
                    )
                )
        return self._revision()

    def finalize(self, session_id: str) -> dict[str, Any]:
        return self.read_state(session_id).controller_state

    def wait_for_revision(self, session_id: str, after_revision: str | None = None) -> ModelRevision:
        return self.read_state(session_id)

