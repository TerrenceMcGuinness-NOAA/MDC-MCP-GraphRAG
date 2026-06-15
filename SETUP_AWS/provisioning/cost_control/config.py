"""Environment -> resource resolution for the Cost_Control_System.

Resolves an :class:`Environment_Name` (``dev`` / ``staging`` / ``prod``) to the
concrete AWS resource identifiers and ARNs the orchestrator operates on (EC2
instance, Neptune cluster, OpenSearch domain, AgentCore runtime, NAT Gateway,
S3 buckets, VPC / subnet / security-group ids). Resolution layers a per-env
default mapping under environment-variable overrides so the same code deploys
isolated dev / staging / prod footprints without edits.

The boto3 session helper mirrors the ingestion scripts' pattern
(``mcp_server_python/scripts/_ingest_common`` + ``src/data/aws_backend``):
``boto3.Session()`` with the region resolved from ``AWS_REGION`` (default
``us-east-1``), so credential / region resolution matches the rest of the
platform tooling.

Requirements: 13.1 (Environment_Name via input), 13.4 (valid_environments
allow-list), 16.1 (artefacts under ``SETUP_AWS/provisioning/``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping, Optional

try:
    import boto3
except ImportError:  # pragma: no cover - boto3 is a hard runtime dependency
    boto3 = None  # type: ignore[assignment]


# ── Allow-list + defaults ──────────────────────────────────────────────────

#: Default ``valid_environments`` allow-list (R13.4). Any other env value is
#: refused by :func:`resolve_config`.
VALID_ENVIRONMENTS: tuple[str, ...] = ("dev", "staging", "prod")

#: Region default matches ``aws_backend.AWS_REGION`` / ``_ingest_common``.
DEFAULT_AWS_REGION: str = "us-east-1"

#: Environment-variable override prefix. Every resolvable field can be
#: overridden via ``COST_CONTROL_<FIELD_UPPER>``; the region additionally
#: honours the platform-standard ``AWS_REGION`` variable.
ENV_PREFIX: str = "COST_CONTROL_"

# Per-env baseline resource ids/ARNs. ``prod`` is populated with the known
# live Phase 53 footprint (see .kiro/steering/01-architecture-context.md and
# 06-python-port-progress.md). ``dev`` / ``staging`` carry only the
# env-suffixed bucket names by default; their compute resource ids are
# expected to come from env-var overrides (or be supplied when those stacks
# are stood up). Buckets follow ``mdc-mcp-rag-cost-control-<purpose>-<env>``.
_ENV_RESOURCE_DEFAULTS: dict[str, dict[str, object]] = {
    "prod": {
        "neptune_cluster_id": "mdc-mcp-graprag-neptune-1",
        "opensearch_domain_name": "mdc-mcp-rag-search",
        "agentcore_runtime_arn": (
            "arn:aws:bedrock-agentcore:us-east-1:903050880929:"
            "runtime/mdc_mcp_rag_server_python-v5K2F8BGrN"
        ),
        "efs_access_point_id": "fsap-03e641f056b341f29",
        "subnet_ids": ["subnet-0e13af6b3a9a6416f", "subnet-04447750c61bd7e06"],
        "security_group_ids": ["sg-096489a0876cc78c1"],
    },
    "staging": {},
    "dev": {},
}

# Fields whose env-var override value is a comma-separated list.
_LIST_FIELDS: frozenset[str] = frozenset({"subnet_ids", "security_group_ids"})

# Scalar fields resolvable from per-env defaults + env-var overrides.
_SCALAR_FIELDS: tuple[str, ...] = (
    "ec2_instance_id",
    "neptune_cluster_id",
    "opensearch_domain_name",
    "agentcore_runtime_arn",
    "nat_gateway_id",
    "vpc_id",
    "efs_access_point_id",
    "state_bucket",
    "audit_bucket",
    "snapshot_bucket",
)


class ConfigError(ValueError):
    """Raised when an environment is outside the allow-list or unresolvable."""


@dataclass(frozen=True)
class EnvironmentConfig:
    """Resolved AWS resource handles for one :class:`Environment_Name`.

    Scalar resource ids may be ``None`` when a non-prod environment has not
    yet had its compute footprint stood up; the orchestrator surfaces a clear
    error at use time rather than at config-resolution time, so ``status`` and
    ``--dry-run`` remain usable before every resource exists.
    """

    environment_name: str
    aws_region: str

    # Compute-tier resources (Compute stack).
    ec2_instance_id: Optional[str] = None
    neptune_cluster_id: Optional[str] = None
    opensearch_domain_name: Optional[str] = None
    agentcore_runtime_arn: Optional[str] = None
    nat_gateway_id: Optional[str] = None

    # Network-tier handles (Network stack).
    vpc_id: Optional[str] = None
    subnet_ids: tuple[str, ...] = field(default_factory=tuple)
    security_group_ids: tuple[str, ...] = field(default_factory=tuple)

    # Storage-tier handles (Storage stack, never destroyed).
    efs_access_point_id: Optional[str] = None
    state_bucket: Optional[str] = None
    audit_bucket: Optional[str] = None
    snapshot_bucket: Optional[str] = None

    @property
    def state_key(self) -> str:
        """S3 key of the authoritative State_File (R8.1, R13.1)."""
        return f"cost-control/{self.environment_name}/state.json"

    @property
    def audit_prefix(self) -> str:
        """S3 key prefix for per-operation audit objects (R9.3, R13.1)."""
        return f"cost-control/{self.environment_name}/"

    @property
    def log_group(self) -> str:
        """CloudWatch log group name (R9.2, R13.1)."""
        return f"mdc-mcp-rag-cost-control-{self.environment_name}"

    @property
    def environment_tag(self) -> dict[str, str]:
        """The ``mdc-mcp-rag:environment`` resource tag (R13.2)."""
        return {"mdc-mcp-rag:environment": self.environment_name}


def _default_bucket(env: str, purpose: str) -> str:
    """Return the default env-suffixed bucket name for a storage purpose."""
    return f"mdc-mcp-rag-cost-control-{purpose}-{env}"


def _override_key(field_name: str) -> str:
    """Map a config field name to its env-var override key."""
    return f"{ENV_PREFIX}{field_name.upper()}"


def resolve_config(
    environment_name: str,
    *,
    env: Optional[Mapping[str, str]] = None,
    valid_environments: tuple[str, ...] = VALID_ENVIRONMENTS,
) -> EnvironmentConfig:
    """Resolve ``environment_name`` to an :class:`EnvironmentConfig`.

    Parameters
    ----------
    environment_name
        The :class:`Environment_Name` (``dev`` / ``staging`` / ``prod``).
    env
        Mapping used for env-var override lookups. Defaults to ``os.environ``.
        Injectable so tests need not mutate the process environment.
    valid_environments
        The ``valid_environments`` allow-list (R13.4). ``environment_name``
        must be a member or :class:`ConfigError` is raised.

    Returns
    -------
    EnvironmentConfig
        Frozen, fully-resolved resource handles.

    Raises
    ------
    ConfigError
        If ``environment_name`` is not in ``valid_environments``.

    Resolution precedence (highest first): env-var override
    (``COST_CONTROL_<FIELD>``) > per-env default > derived default (buckets) /
    ``None``.
    """
    if env is None:
        env = os.environ

    if environment_name not in valid_environments:
        allowed = ", ".join(valid_environments)
        raise ConfigError(
            f"environment_name {environment_name!r} is not in the "
            f"valid_environments allow-list ({allowed})"
        )

    defaults = _ENV_RESOURCE_DEFAULTS.get(environment_name, {})

    # Region: AWS_REGION (platform standard) then COST_CONTROL_AWS_REGION,
    # then the us-east-1 default.
    aws_region = (
        env.get(_override_key("aws_region"))
        or env.get("AWS_REGION")
        or DEFAULT_AWS_REGION
    )

    # Scalar fields: env-var override > per-env default > derived/None.
    resolved: dict[str, object] = {}
    for name in _SCALAR_FIELDS:
        override = env.get(_override_key(name))
        if override is not None:
            resolved[name] = override
            continue
        if name in defaults:
            resolved[name] = defaults[name]
            continue
        resolved[name] = None

    # Storage buckets fall back to a derived env-suffixed default rather than
    # None so the State_File / audit / snapshot keys always have a home.
    for name, purpose in (
        ("state_bucket", "state"),
        ("audit_bucket", "audit"),
        ("snapshot_bucket", "snapshots"),
    ):
        if resolved[name] is None:
            resolved[name] = _default_bucket(environment_name, purpose)

    # List fields: comma-separated override > per-env default list > ().
    list_resolved: dict[str, tuple[str, ...]] = {}
    for name in _LIST_FIELDS:
        override = env.get(_override_key(name))
        if override is not None:
            items = tuple(s.strip() for s in override.split(",") if s.strip())
        else:
            default_list = defaults.get(name) or []
            items = tuple(default_list)  # type: ignore[arg-type]
        list_resolved[name] = items

    return EnvironmentConfig(
        environment_name=environment_name,
        aws_region=aws_region,
        ec2_instance_id=resolved["ec2_instance_id"],  # type: ignore[arg-type]
        neptune_cluster_id=resolved["neptune_cluster_id"],  # type: ignore[arg-type]
        opensearch_domain_name=resolved["opensearch_domain_name"],  # type: ignore[arg-type]
        agentcore_runtime_arn=resolved["agentcore_runtime_arn"],  # type: ignore[arg-type]
        nat_gateway_id=resolved["nat_gateway_id"],  # type: ignore[arg-type]
        vpc_id=resolved["vpc_id"],  # type: ignore[arg-type]
        subnet_ids=list_resolved["subnet_ids"],
        security_group_ids=list_resolved["security_group_ids"],
        efs_access_point_id=resolved["efs_access_point_id"],  # type: ignore[arg-type]
        state_bucket=resolved["state_bucket"],  # type: ignore[arg-type]
        audit_bucket=resolved["audit_bucket"],  # type: ignore[arg-type]
        snapshot_bucket=resolved["snapshot_bucket"],  # type: ignore[arg-type]
    )


def build_session(
    *,
    region_name: Optional[str] = None,
    profile_name: Optional[str] = None,
):
    """Build a boto3 Session, mirroring the ingestion scripts' pattern.

    Region resolution order: explicit ``region_name`` argument > ``AWS_REGION``
    env var > :data:`DEFAULT_AWS_REGION`. ``profile_name`` is honoured when
    supplied (CI / operator workstation profiles) and otherwise left to the
    default credential chain, exactly as ``aws_backend`` does with
    ``boto3.Session()``.

    Raises
    ------
    RuntimeError
        If boto3 is not importable (it is a hard runtime dependency).
    """
    if boto3 is None:  # pragma: no cover - import guard
        raise RuntimeError("boto3 is required but not importable")
    region = region_name or os.environ.get("AWS_REGION", DEFAULT_AWS_REGION)
    if profile_name:
        return boto3.Session(region_name=region, profile_name=profile_name)
    return boto3.Session(region_name=region)


def client(service_name: str, config: EnvironmentConfig, *, session=None):
    """Return a boto3 client for ``service_name`` bound to the config region.

    A pre-built ``session`` may be injected (tests pass a session whose clients
    are wrapped in a ``botocore`` Stubber); otherwise one is built via
    :func:`build_session`.
    """
    if session is None:
        session = build_session(region_name=config.aws_region)
    return session.client(service_name, region_name=config.aws_region)
