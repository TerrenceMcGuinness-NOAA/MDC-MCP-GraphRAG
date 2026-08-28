"""Default-tenant byte-equivalence baseline package.

Holds the one-shot capture harness (:mod:`tests.baselines.capture`), the
frozen recorded adapter responses (``recorded_backend/``), the rendered
pre-change baselines and volatility masks (``pre_change/``), and the
regeneration procedure (``README.md``).

shared-scope-query-routing Task 6. The captures record the behaviour of
the revision immediately preceding the read-path routing change so that
Requirement 6.5 (default-tenant byte-equivalence) is verifiable against a
valid parent revision.
"""
