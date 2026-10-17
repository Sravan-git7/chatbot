"""Canonical public API statuses shared by the service and mechanical evaluators.

The legacy ``page_not_ingested`` token remains in the frozen workload's declared
vocabulary for compatibility, but it is an internal pipeline state, not a valid
public response status. The service maps it to ``documentation_unavailable``.
"""
from __future__ import annotations

ANSWERED = "answered"
DOCUMENTATION_UNAVAILABLE = "documentation_unavailable"
UNABLE_TO_VERIFY = "unable_to_verify"
OUT_OF_SCOPE = "out_of_scope"
NO_ADDITIONAL_VERIFIED_EVIDENCE = "no_additional_verified_evidence"

API_STATUSES = (
    ANSWERED,
    DOCUMENTATION_UNAVAILABLE,
    UNABLE_TO_VERIFY,
    OUT_OF_SCOPE,
    NO_ADDITIONAL_VERIFIED_EVIDENCE,
)

# Frozen v1/v2 workload files retain one historical internal pipeline status
# and predate the later ``no_additional_verified_evidence`` API state. Preserve
# that exact declaration contract; item expected_status values are independently
# checked against API_STATUSES above, never against this workload-supplied list.
WORKLOAD_STATUS_VOCABULARY = frozenset({
    ANSWERED, DOCUMENTATION_UNAVAILABLE, UNABLE_TO_VERIFY, OUT_OF_SCOPE, "page_not_ingested",
})
