"""AgentCore Runtime tier (Task 10).

The runtime *definition* is free when idle (sessions auto-terminate at the
15-min idle timeout), so hibernate is a no-op: deleting it would force a full
recreate on wake for zero savings. The tier records the runtime ARN, runtime
id, container image URI, and image digest in the manifest so drift detection
notices if the runtime or image changed while the platform was asleep; wake
re-points the DEFAULT endpoint via ``update_agent_runtime`` only when the
captured manifest differs from the live runtime.

Uses the boto3 ``bedrock-agentcore-control`` client (the ``aws-agentcore``
power's ``get_agent_runtime`` / ``update_agent_runtime`` surface). ECR image
digests come from the ``ecr`` client.

Requirements: 1.3, 3.x (storage immutability -- AgentCore mutates nothing on
hibernate).
"""

from __future__ import annotations

from typing import Any, Optional

from cost_control.config import EnvironmentConfig
from cost_control.tiers import PlannedAction, TierError


def _runtime_id_from_arn(arn: str) -> str:
    """Extract the runtime id (segment after ``runtime/``) from an ARN."""
    marker = "runtime/"
    idx = arn.find(marker)
    if idx == -1:
        # Fall back to the trailing path segment.
        return arn.rsplit("/", 1)[-1]
    return arn[idx + len(marker):]


class AgentCoreTier:
    """Sleep/wake control for the AgentCore Runtime (no-op hibernate)."""

    name = "agentcore"

    def __init__(
        self,
        config: EnvironmentConfig,
        runtime_client: Any,
        *,
        ecr_client: Any = None,
        repository_name: str = "mdc-mcp-rag",
        operation_id: str = "",
        audit: Any = None,
        expected_manifest: Optional[dict[str, Any]] = None,
    ) -> None:
        if not config.agentcore_runtime_arn:
            raise TierError("AgentCoreTier requires config.agentcore_runtime_arn")
        self._cfg = config
        self._rt = runtime_client
        self._ecr = ecr_client
        self._repo = repository_name
        self._op = operation_id
        self._audit = audit
        self._expected_manifest = expected_manifest

    @property
    def runtime_arn(self) -> str:
        return self._cfg.agentcore_runtime_arn  # type: ignore[return-value]

    @property
    def runtime_id(self) -> str:
        return _runtime_id_from_arn(self.runtime_arn)

    # -- helpers -----------------------------------------------------------

    def _get_runtime(self) -> dict[str, Any]:
        return self._rt.get_agent_runtime(agentRuntimeId=self.runtime_id)

    def _container_uri(self, runtime: dict[str, Any]) -> Optional[str]:
        artifact = runtime.get("agentRuntimeArtifact", {}) or {}
        container = artifact.get("containerConfiguration", {}) or {}
        return container.get("containerUri")

    def _image_digest(self, container_uri: Optional[str]) -> Optional[str]:
        if not container_uri or self._ecr is None:
            return None
        # containerUri ends with ...:<tag> ; resolve that tag's digest.
        tag = container_uri.rsplit(":", 1)[-1] if ":" in container_uri else None
        if not tag:
            return None
        resp = self._ecr.describe_images(
            repositoryName=self._repo, imageIds=[{"imageTag": tag}]
        )
        details = resp.get("imageDetails", [])
        return details[0].get("imageDigest") if details else None

    def _emit(self, event_type: str, **kwargs: Any) -> None:
        if self._audit is not None:
            self._audit.emit(event_type, tier=self.name, **kwargs)

    # -- Tier interface ----------------------------------------------------

    def is_asleep(self) -> bool:
        # The definition is always present; there is no asleep shape. Hibernate
        # is a no-op, so report True to satisfy idempotent skip logic.
        return True

    def capture_manifest(self) -> dict[str, Any]:
        runtime = self._get_runtime()
        container_uri = self._container_uri(runtime)
        return {
            "runtime_arn": runtime.get("agentRuntimeArn", self.runtime_arn),
            "runtime_id": self.runtime_id,
            "container_uri": container_uri,
            "image_digest": self._image_digest(container_uri),
            "status": runtime.get("status"),
        }

    def plan(self, mode: str) -> list[PlannedAction]:
        return [
            PlannedAction(self.name, "noop",
                          "AgentCore runtime definition is free when idle; "
                          "no action", destructive=False, target=self.runtime_arn),
        ]

    def hibernate(self) -> list[PlannedAction]:
        # No-op: the runtime definition incurs no hourly charge.
        self._emit("Tier_Skipped", state_before="idle", state_after="idle",
                   aws_resource_arns=[self.runtime_arn])
        return []

    def wake(self) -> list[PlannedAction]:
        """Re-point the DEFAULT endpoint only if the live runtime drifted.

        With no ``expected_manifest`` (no drift comparison requested) this is a
        no-op. When the expected manifest's container image digest differs from
        the live runtime, ``update_agent_runtime`` re-points the runtime,
        reusing the live ``roleArn`` and ``networkConfiguration`` (both
        required by the API) and swapping only the container artifact.
        """
        if self._expected_manifest is None:
            return []
        runtime = self._get_runtime()
        current_digest = self._image_digest(self._container_uri(runtime))
        expected_digest = self._expected_manifest.get("image_digest")
        if expected_digest and current_digest == expected_digest:
            # Unchanged -- nothing to re-point.
            return []

        artifact = {
            "containerConfiguration": {
                "containerUri": self._expected_manifest.get("container_uri"),
            }
        }
        self._rt.update_agent_runtime(
            agentRuntimeId=self.runtime_id,
            agentRuntimeArtifact=artifact,
            roleArn=runtime["roleArn"],
            networkConfiguration=runtime["networkConfiguration"],
        )
        self._emit("Runtime_Repointed", aws_resource_arns=[self.runtime_arn])
        return [
            PlannedAction(self.name, "update_agent_runtime",
                          "Re-pointed AgentCore DEFAULT endpoint after drift",
                          target=self.runtime_arn),
        ]
