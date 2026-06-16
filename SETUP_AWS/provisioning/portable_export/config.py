"""Environment -> resource resolution for the Cross_Platform_Data_Persistence_System.

Resolves an :class:`Environment_Name` (``dev`` / ``staging`` / ``prod``) to the
concrete handles the pipeline operates on:

* the S3 ``portable_export_bucket`` that stages the Portable_Export,
* the optional ``kms_key_arn`` for SSE-KMS object writes,
* the source AWS endpoints (``opensearch_endpoint``, ``neptune_endpoint``),
* the :class:`Tenant_Catalog` parsed from
  ``mcp_server_python/src/config/tenants.yaml`` with PyYAML, and
* the :class:`Model_Profile` registry (embedding dimensions per profile).

Resolution layers a per-env default mapping under environment-variable
overrides so the same code stages isolated dev / staging / prod exports
without edits.

The boto3 session helper mirrors the ingestion scripts' pattern
(``mcp_server_python/scripts/_ingest_common`` + ``src/data/aws_backend``):
``boto3.Session()`` with the region resolved from ``AWS_REGION`` (default
``us-east-1``).

Requirements: 11.1 (manifest source endpoints), 15.4 (provisioning directory),
7.1 (tenant enumeration).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

import yaml

try:
    import boto3
except ImportError:  # pragma: no cover - boto3 is a hard runtime dependency
    boto3 = None  # type: ignore[assignment]


# ── Allow-list + defaults ──────────────────────────────────────────────────

#: ``valid_environments`` allow-list, matching ``nih-sandbox-cost-control``.
VALID_ENVIRONMENTS: tuple[str, ...] = ("dev", "staging", "prod")

#: Region default matches ``aws_backend.AWS_REGION`` / ``_ingest_common``.
DEFAULT_AWS_REGION: str = "us-east-1"

#: Default S3 bucket for staged Portable_Export artifacts (overridable via
#: ``PORTABLE_EXPORT_BUCKET``).
DEFAULT_PORTABLE_EXPORT_BUCKET: str = "mdc-mcp-rag-snapshots-903050880929"

#: Environment-variable override prefix for pipeline-specific fields. The
#: region, bucket, and endpoint additionally honour the platform-standard
#: bare variable names (``AWS_REGION`` / ``PORTABLE_EXPORT_BUCKET`` /
#: ``OPENSEARCH_ENDPOINT`` / ``NEPTUNE_ENDPOINT``).
ENV_PREFIX: str = "PORTABLE_EXPORT_"

#: Default path to the tenant catalog, relative to the repository root
#: (``SETUP_AWS/provisioning/portable_export/`` -> repo root is parents[3]).
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TENANTS_YAML: Path = (
    _REPO_ROOT / "mcp_server_python" / "src" / "config" / "tenants.yaml"
)

#: Known live source endpoints (reference only; resolved from env in prod).
_KNOWN_OPENSEARCH_ENDPOINT = (
    "https://vpc-mdc-mcp-rag-search-5o72hixfx3rryikwb7l5px5sgq."
    "us-east-1.es.amazonaws.com"
)
_KNOWN_NEPTUNE_ENDPOINT = (
    "https://mdc-mcp-graprag-neptune-1.cluster-ccdaimu4c86s."
    "us-east-1.neptune.amazonaws.com:8182"
)

_ENV_RESOURCE_DEFAULTS: dict[str, dict[str, object]] = {
    "prod": {
        "opensearch_endpoint": _KNOWN_OPENSEARCH_ENDPOINT,
        "neptune_endpoint": _KNOWN_NEPTUNE_ENDPOINT,
        "dedupe_table": "mdc-content-sha-registry",
    },
    "staging": {},
    "dev": {},
}


# ── Model_Profile registry ─────────────────────────────────────────────────
# Embedding-model descriptors used to size the per-Model_Profile knn_vector
# mapping and to populate the Export_Manifest's ``model_profiles`` block.
# Values are copied verbatim from
# ``mcp_server_python/src/data/embedding_registry.py`` -- keep in sync if a
# built-in profile there changes (the on-disk index naming depends on these
# exact dimensions / model_id strings).


@dataclass(frozen=True)
class ModelProfile:
    """Immutable embedding-model descriptor (R4.2)."""

    short_name: str
    provider: str
    model_id: str
    dimensions: int


MODEL_PROFILES: dict[str, ModelProfile] = {
    "mpnet768": ModelProfile("mpnet768", "local", "all-mpnet-base-v2", 768),
    "titan1024": ModelProfile(
        "titan1024", "bedrock", "amazon.titan-embed-text-v2:0", 1024
    ),
    "nova256": ModelProfile(
        "nova256", "bedrock", "amazon.nova-2-multimodal-embeddings-v1:0", 256
    ),
    "nova512": ModelProfile(
        "nova512", "bedrock", "amazon.nova-2-multimodal-embeddings-v1:0", 512
    ),
    "nova1024": ModelProfile(
        "nova1024", "bedrock", "amazon.nova-2-multimodal-embeddings-v1:0", 1024
    ),
    "nova3072": ModelProfile(
        "nova3072", "bedrock", "amazon.nova-2-multimodal-embeddings-v1:0", 3072
    ),
}


def model_profile(short_name: str) -> ModelProfile:
    """Return the :class:`ModelProfile` named ``short_name``.

    Raises
    ------
    ConfigError
        If ``short_name`` is not a registered profile. The message lists
        every registered profile so callers can surface a clear diagnostic.
    """
    profile = MODEL_PROFILES.get(short_name)
    if profile is None:
        raise ConfigError(
            f"unknown model_profile {short_name!r}; "
            f"registered: {sorted(MODEL_PROFILES)}"
        )
    return profile


def model_profile_dimensions(short_name: str) -> int:
    """Return the embedding dimension for ``short_name`` (R3.3, R4.2)."""
    return model_profile(short_name).dimensions


def infer_model_profile(collection_name: str) -> Optional[str]:
    """Infer the Model_Profile short name from a model-aware collection name.

    Production collections carry the profile as a suffix
    (``mdc-code-context-titan1024``). Returns ``None`` when no known profile
    suffix is present (legacy / unmapped collections).
    """
    for name in MODEL_PROFILES:
        if collection_name.endswith(f"-{name}") or collection_name.endswith(name):
            # Require a separator so 'titan1024' does not match inside a word.
            if collection_name == name or collection_name.endswith(f"-{name}"):
                return name
    return None


# ── Tenant_Catalog ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Tenant:
    """A single tenant entry parsed from ``tenants.yaml`` (R7.1-R7.3).

    Only the fields the pipeline needs are kept: identity plus the index
    and label prefixes that scope the Index_Family / label family.
    """

    tenant_id: str
    index_prefix: str
    label_prefix: str
    lifecycle: str = "experimental"
    description: str = ""

    @property
    def is_default(self) -> bool:
        """True for the unprefixed baseline tenant (``gw``) (R7.2)."""
        return self.index_prefix == "" and self.label_prefix == ""


@dataclass(frozen=True)
class TenantCatalog:
    """The parsed tenant catalog (R7.1)."""

    schema_version: int
    default_tenant_id: str
    tenants: tuple[Tenant, ...]

    def by_id(self, tenant_id: str) -> Optional[Tenant]:
        """Look up a tenant by ID; ``None`` if absent."""
        return next((t for t in self.tenants if t.tenant_id == tenant_id), None)

    @property
    def tenant_ids(self) -> tuple[str, ...]:
        """All tenant IDs in catalog order."""
        return tuple(t.tenant_id for t in self.tenants)


def load_tenant_catalog(path: str | Path | None = None) -> TenantCatalog:
    """Load and parse ``tenants.yaml`` with PyYAML.

    Parameters
    ----------
    path
        Path to the catalog. Defaults to :data:`DEFAULT_TENANTS_YAML`.

    Returns
    -------
    TenantCatalog
        The parsed catalog (structural validation beyond field presence is
        left to the authoritative ``src.config.tenants`` loader).

    Raises
    ------
    ConfigError
        If the file is missing, unparseable, or has no ``tenants`` list.
    """
    catalog_path = Path(path) if path is not None else DEFAULT_TENANTS_YAML
    try:
        raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"tenant catalog not found: {catalog_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"tenant catalog YAML parse error: {exc}") from exc

    if not isinstance(raw, dict) or "tenants" not in raw:
        raise ConfigError(
            f"tenant catalog {catalog_path} has no 'tenants' list"
        )

    defaults_raw = raw.get("defaults") or {}
    tenants: list[Tenant] = []
    for entry in raw.get("tenants") or []:
        tenants.append(
            Tenant(
                tenant_id=entry["tenant_id"],
                index_prefix=entry.get("index_prefix", ""),
                label_prefix=entry.get("label_prefix", ""),
                lifecycle=entry.get("lifecycle", "experimental"),
                description=(entry.get("description", "") or "").strip(),
            )
        )
    return TenantCatalog(
        schema_version=int(raw.get("schema_version", 1)),
        default_tenant_id=defaults_raw.get("tenant_id", "gw"),
        tenants=tuple(tenants),
    )


# ── Environment config ──────────────────────────────────────────────────────


class ConfigError(ValueError):
    """Raised when an environment is outside the allow-list or unresolvable."""


@dataclass(frozen=True)
class EnvironmentConfig:
    """Resolved handles for one :class:`Environment_Name`.

    Source endpoints may be ``None`` when a non-prod environment has not had
    its footprint stood up; the pipeline surfaces a clear error at use time
    rather than at resolution time so ``status`` / ``--dry-run`` remain usable.
    """

    environment_name: str
    aws_region: str
    portable_export_bucket: str
    kms_key_arn: Optional[str] = None
    opensearch_endpoint: Optional[str] = None
    neptune_endpoint: Optional[str] = None
    dedupe_table: Optional[str] = None
    catalog: Optional[TenantCatalog] = None

    @property
    def audit_log_group(self) -> str:
        """CloudWatch log group for portable-export audit (Task 2)."""
        return f"mdc-mcp-rag-portable-export-{self.environment_name}"

    def default_prefix(self, manifest_id: str) -> str:
        """Default S3 key prefix for a Portable_Export with ``manifest_id``."""
        return f"portable-export/{self.environment_name}/{manifest_id}/"

    @property
    def environment_tag(self) -> dict[str, str]:
        """The ``mdc-mcp-rag:environment`` resource tag."""
        return {"mdc-mcp-rag:environment": self.environment_name}


def _override_key(field_name: str) -> str:
    """Map a config field name to its prefixed env-var override key."""
    return f"{ENV_PREFIX}{field_name.upper()}"


def resolve_config(
    environment_name: str,
    *,
    env: Optional[Mapping[str, str]] = None,
    valid_environments: tuple[str, ...] = VALID_ENVIRONMENTS,
    tenants_path: str | Path | None = None,
    load_catalog: bool = True,
) -> EnvironmentConfig:
    """Resolve ``environment_name`` to an :class:`EnvironmentConfig`.

    Parameters
    ----------
    environment_name
        The :class:`Environment_Name` (``dev`` / ``staging`` / ``prod``).
    env
        Mapping for env-var override lookups. Defaults to ``os.environ``.
        Injectable so tests need not mutate the process environment.
    valid_environments
        The allow-list; ``environment_name`` must be a member (R13.4 parity).
    tenants_path
        Override path to ``tenants.yaml`` (tests inject a fixture).
    load_catalog
        When ``True`` (default) the tenant catalog is parsed and attached.

    Returns
    -------
    EnvironmentConfig
        Frozen, fully-resolved handles.

    Raises
    ------
    ConfigError
        If ``environment_name`` is not in ``valid_environments``.

    Resolution precedence (highest first): prefixed override
    (``PORTABLE_EXPORT_<FIELD>``) > bare platform var (region / bucket /
    endpoints) > per-env default > derived default / ``None``.
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

    aws_region = (
        env.get(_override_key("aws_region"))
        or env.get("AWS_REGION")
        or DEFAULT_AWS_REGION
    )

    portable_export_bucket = (
        env.get(_override_key("bucket"))
        or env.get("PORTABLE_EXPORT_BUCKET")
        or str(defaults.get("portable_export_bucket", ""))
        or DEFAULT_PORTABLE_EXPORT_BUCKET
    )

    kms_key_arn = (
        env.get(_override_key("kms_key_arn"))
        or env.get("PORTABLE_EXPORT_KMS_KEY_ARN")
        or (str(defaults["kms_key_arn"]) if "kms_key_arn" in defaults else None)
    )

    opensearch_endpoint = (
        env.get(_override_key("opensearch_endpoint"))
        or env.get("OPENSEARCH_ENDPOINT")
        or (
            str(defaults["opensearch_endpoint"])
            if "opensearch_endpoint" in defaults
            else None
        )
    )

    neptune_endpoint = (
        env.get(_override_key("neptune_endpoint"))
        or env.get("NEPTUNE_ENDPOINT")
        or (
            str(defaults["neptune_endpoint"])
            if "neptune_endpoint" in defaults
            else None
        )
    )

    dedupe_table = (
        env.get(_override_key("dedupe_table"))
        or env.get("PORTABLE_EXPORT_DEDUPE_TABLE")
        or str(defaults.get("dedupe_table", "mdc-content-sha-registry"))
    )

    catalog = load_tenant_catalog(tenants_path) if load_catalog else None

    return EnvironmentConfig(
        environment_name=environment_name,
        aws_region=aws_region,
        portable_export_bucket=portable_export_bucket,
        kms_key_arn=kms_key_arn,
        opensearch_endpoint=opensearch_endpoint,
        neptune_endpoint=neptune_endpoint,
        dedupe_table=dedupe_table,
        catalog=catalog,
    )


def build_session(
    *,
    region_name: Optional[str] = None,
    profile_name: Optional[str] = None,
):
    """Build a boto3 Session, mirroring the ingestion scripts' pattern.

    Region resolution order: explicit ``region_name`` > ``AWS_REGION`` env var
    > :data:`DEFAULT_AWS_REGION`. ``profile_name`` is honoured when supplied
    and otherwise left to the default credential chain, exactly as
    ``aws_backend`` does with ``boto3.Session()``.

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
