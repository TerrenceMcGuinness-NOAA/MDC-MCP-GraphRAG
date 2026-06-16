"""Query_Embedder availability check (Task 5).

A restore target can *load* every Model_Profile's vectors bitwise (the data
transfer never re-embeds), but it can only serve meaningful similarity search
for a Model_Profile when it has access to a matching Query_Embedder. This
module computes, per Model_Profile, whether the target is ``Query_Compatible``
or ``Query_Incompatible`` and surfaces the flags so the restore completes the
load regardless (R4.5) while reporting which profiles cannot be queried (R4.4).

Availability matrix (design):

================================  ========  =========  =====================
Restore target                    mpnet768  titan1024  nova{256,512,1024,3072}
================================  ========  =========  =====================
AWS (``AWS_Reimport``)            yes       yes        yes
COTS with Bedrock IAM             yes       yes        yes
COTS without Bedrock              yes       NO         NO
================================  ========  =========  =====================

* ``mpnet768`` is locally embeddable (sentence-transformers) everywhere.
* ``titan1024`` / ``nova*`` are Bedrock-only, so a COTS host without Bedrock
  IAM is ``Query_Incompatible`` for them.

Requirements: 4.3, 4.4, 4.5.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

#: Profiles that can be embedded locally (no Bedrock required).
LOCAL_EMBEDDABLE_PROFILES: frozenset[str] = frozenset({"mpnet768"})

#: Profiles that require Bedrock at query time.
BEDROCK_PROFILES: frozenset[str] = frozenset(
    {"titan1024", "nova256", "nova512", "nova1024", "nova3072"}
)

QUERY_COMPATIBLE = "Query_Compatible"
QUERY_INCOMPATIBLE = "Query_Incompatible"


@dataclass(frozen=True)
class CompatibilityResult:
    """Per-target Query_Embedder compatibility outcome."""

    target: str
    has_bedrock: bool
    per_profile: dict[str, str]

    @property
    def incompatible_profiles(self) -> list[str]:
        """Profiles flagged Query_Incompatible (data loaded, cannot query)."""
        return sorted(
            p for p, status in self.per_profile.items()
            if status == QUERY_INCOMPATIBLE
        )

    @property
    def all_compatible(self) -> bool:
        return not self.incompatible_profiles


def profile_compatibility(
    model_profile: str, *, target: str, has_bedrock: bool
) -> str:
    """Return ``Query_Compatible`` / ``Query_Incompatible`` for one profile.

    Parameters
    ----------
    model_profile
        Profile short name (e.g. ``"titan1024"``).
    target
        ``"aws"`` or ``"cots"``.
    has_bedrock
        Whether the target has Bedrock IAM access. Ignored for ``aws`` (AWS
        always has Bedrock + local) and for locally-embeddable profiles.
    """
    if model_profile in LOCAL_EMBEDDABLE_PROFILES:
        return QUERY_COMPATIBLE
    if target == "aws":
        # AWS reimport target always has Bedrock for titan/nova.
        return QUERY_COMPATIBLE
    # COTS target: Bedrock-only profiles need Bedrock IAM.
    return QUERY_COMPATIBLE if has_bedrock else QUERY_INCOMPATIBLE


def check_compatibility(
    model_profiles: Iterable[str],
    *,
    target: str,
    has_bedrock: bool,
) -> CompatibilityResult:
    """Compute compatibility for every restored Model_Profile.

    Parameters
    ----------
    model_profiles
        The set of Model_Profiles present in the Portable_Export.
    target
        ``"aws"`` or ``"cots"``.
    has_bedrock
        Whether the target has Bedrock IAM (always treated true for ``aws``).

    Returns
    -------
    CompatibilityResult
        Per-profile flags; ``Query_Incompatible`` never blocks the restore.
    """
    effective_bedrock = has_bedrock or target == "aws"
    per_profile = {
        p: profile_compatibility(p, target=target, has_bedrock=effective_bedrock)
        for p in dict.fromkeys(model_profiles)  # de-dup, preserve order
    }
    return CompatibilityResult(
        target=target, has_bedrock=effective_bedrock, per_profile=per_profile
    )


__all__ = [
    "CompatibilityResult",
    "check_compatibility",
    "profile_compatibility",
    "QUERY_COMPATIBLE",
    "QUERY_INCOMPATIBLE",
    "LOCAL_EMBEDDABLE_PROFILES",
    "BEDROCK_PROFILES",
]
