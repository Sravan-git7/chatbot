# Phase 13-B: Per-Question Comparison Diff (Guarded Ollama)

| ID | Type | Gold Card | Baseline Top-1 | Reranked Top-1 | Sel Changed | Base Status -> Rerank Status | Base Correct -> Rerank Correct | Failure Reason (Reranked) |
|---|---|---|---|---|:---:|---|:---:|---|
| P12-001 | answerable | M2C-07 | M2C-22 | M2C-22 | - | insufficient_context -> insufficient_context | False | LOW_QUERY_TERM_COVERAGE_IN_CONTEXT |
| P12-002 | answerable | M2C-07 | M2C-25 | M2C-25 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-003 | answerable | M2C-07 | M2C-07 | M2C-07 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-004 | answerable | M2C-05 | M2C-05 | M2C-05 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-005 | answerable | M2C-05 | M2C-05 | M2C-05 | - | answered -> answered | True | answerable_answered_correct |
| P12-006 | answerable | M2C-05 | M2C-27 | M2C-05 | YES | insufficient_context -> answered | False | answerable_answered_citation_evidence_failure |
| P12-007 | answerable | M2C-24 | M2C-20 | M2C-20 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-008 | answerable | M2C-24 | M2C-20 | M2C-24 | YES | out_of_domain -> answered | False -> **True** | answerable_answered_correct |
| P12-009 | answerable | M2C-14 | M2C-14 | M2C-14 | - | answered -> answered | True | answerable_answered_correct |
| P12-010 | answerable | M2C-14 | M2C-29 | M2C-14 | YES | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-011 | answerable | M2C-17 | M2C-18 | M2C-17 | YES | unresolved_identity -> answered | False -> **True** | answerable_answered_correct |
| P12-012 | answerable | M2C-11 | M2C-11 | M2C-11 | - | answered -> answered | True | answerable_answered_correct |
| P12-013 | answerable | M2C-02 | M2C-04 | M2C-04 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-014 | answerable | M2C-02 | M2C-03 | M2C-02 | YES | answered -> answered | False -> **True** | answerable_answered_correct |
| P12-015 | answerable | M2C-07 | M2C-06 | M2C-06 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-016 | answerable | M2C-07 | M2C-07 | M2C-07 | - | answered -> answered | True | answerable_answered_correct |
| P12-017 | answerable | M2C-24 | M2C-24 | M2C-24 | - | insufficient_context -> insufficient_context | False | LOW_QUERY_TERM_COVERAGE_IN_CONTEXT |
| P12-018 | answerable | M2C-24 | M2C-24 | M2C-24 | - | insufficient_context -> insufficient_context | False | LOW_QUERY_TERM_COVERAGE_IN_CONTEXT |
| P12-019 | answerable | M2C-14 | M2C-14 | M2C-14 | - | answered -> answered | True | answerable_answered_correct |
| P12-020 | answerable | M2C-14 | M2C-14 | M2C-14 | - | answered -> answered | True | answerable_answered_correct |
| P12-021 | answerable | M2C-17 | M2C-17 | M2C-17 | - | answered -> answered | True | answerable_answered_correct |
| P12-022 | answerable | M2C-17 | M2C-01 | M2C-03 | YES | unresolved_identity -> insufficient_context | False | GENERATOR_REFUSED |
| P12-023 | answerable | M2C-11 | M2C-13 | M2C-11 | YES | out_of_domain -> answered | False -> **True** | answerable_answered_correct |
| P12-024 | answerable | M2C-02 | M2C-03 | M2C-02 | YES | insufficient_context -> insufficient_context | False | LOW_QUERY_TERM_COVERAGE_IN_CONTEXT |
| P12-025 | answerable | M2C-05 | M2C-05 | M2C-05 | - | answered -> answered | True | answerable_answered_correct |
| P12-026 | answerable | M2C-07 | M2C-06 | M2C-07 | YES | insufficient_context -> answered | False | answerable_answered_citation_evidence_failure |
| P12-027 | answerable | M2C-07 | M2C-03 | M2C-05 | YES | insufficient_context -> answered | False | answerable_answered_wrong_page |
| P12-028 | answerable | M2C-05 | M2C-05 | M2C-05 | - | answered -> answered | True | answerable_answered_correct |
| P12-029 | answerable | M2C-24 | M2C-24 | M2C-24 | - | answered -> answered | True | answerable_answered_correct |
| P12-030 | answerable | M2C-24 | M2C-27 | M2C-05 | YES | out_of_domain -> out_of_domain | False | LOW_QUERY_TERM_COVERAGE_VS_ROUTED_TOPIC |
| P12-031 | answerable | M2C-14 | M2C-13 | M2C-15 | YES | unresolved_identity -> insufficient_context | False | GENERATOR_REFUSED |
| P12-032 | answerable | M2C-17 | M2C-18 | M2C-17 | YES | unresolved_identity -> answered | False -> **True** | answerable_answered_correct |
| P12-033 | answerable | M2C-11 | M2C-12 | M2C-11 | YES | insufficient_context -> answered | False -> **True** | answerable_answered_correct |
| P12-034 | answerable | M2C-02 | M2C-04 | M2C-03 | YES | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-035 | answerable | M2C-07 | M2C-06 | M2C-07 | YES | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-036 | answerable | M2C-07 | M2C-10 | M2C-07 | YES | insufficient_context -> answered | False -> **True** | answerable_answered_correct |
| P12-037 | answerable | M2C-07 | M2C-10 | M2C-07 | YES | insufficient_context -> answered | False -> **True** | answerable_answered_correct |
| P12-038 | answerable | M2C-07 | M2C-27 | M2C-09 | YES | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-039 | answerable | M2C-07 | M2C-10 | M2C-07 | YES | insufficient_context -> answered | False -> **True** | answerable_answered_correct |
| P12-040 | answerable | M2C-24 | M2C-24 | M2C-24 | - | answered -> answered | True | answerable_answered_correct |
| P12-041 | answerable | M2C-24 | M2C-20 | M2C-21 | YES | out_of_domain -> insufficient_context | False | GENERATOR_REFUSED |
| P12-042 | answerable | M2C-05 | M2C-23 | M2C-17 | YES | out_of_domain -> insufficient_context | False | LOW_QUERY_TERM_COVERAGE_IN_CONTEXT |
| P12-043 | answerable | M2C-02 | M2C-03 | M2C-02 | YES | insufficient_context -> answered | False -> **True** | answerable_answered_correct |
| P12-044 | answerable | M2C-24 | M2C-24 | M2C-24 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-045 | answerable | M2C-24 | M2C-24 | M2C-25 | YES | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-046 | answerable | M2C-24 | M2C-24 | M2C-24 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-047 | answerable | M2C-24 | M2C-27 | M2C-27 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-048 | answerable | M2C-24 | M2C-24 | M2C-24 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-049 | answerable | M2C-07 | M2C-07 | M2C-07 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-050 | answerable | M2C-24 | M2C-25 | M2C-24 | YES | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-051 | answerable | M2C-24 | M2C-25 | M2C-24 | YES | answered -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-052 | answerable | M2C-02 | M2C-04 | M2C-02 | YES | answered -> answered | False -> **True** | answerable_answered_correct |
| P12-053 | answerable | M2C-07 | M2C-07 | M2C-07 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-054 | answerable | M2C-11 | M2C-12 | M2C-11 | YES | insufficient_context -> answered | False -> **True** | answerable_answered_correct |
| P12-055 | answerable | M2C-14 | M2C-14 | M2C-14 | - | answered -> answered | True | answerable_answered_correct |
| P12-056 | answerable | M2C-17 | M2C-18 | M2C-17 | YES | unresolved_identity -> answered | False -> **True** | answerable_answered_correct |
| P12-057 | answerable | M2C-05 | M2C-05 | M2C-05 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-058 | answerable | M2C-05 | M2C-05 | M2C-05 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-059 | answerable | M2C-05 | M2C-05 | M2C-05 | - | answered -> answered | True | answerable_answered_correct |
| P12-060 | answerable | M2C-05 | M2C-05 | M2C-05 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-061 | answerable | M2C-05 | M2C-05 | M2C-05 | - | answered -> answered | True | answerable_answered_correct |
| P12-062 | answerable | M2C-05 | M2C-05 | M2C-05 | - | answered -> answered | True | answerable_answered_correct |
| P12-063 | answerable | M2C-05 | M2C-05 | M2C-05 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-064 | answerable | M2C-14 | M2C-04 | M2C-14 | YES | out_of_domain -> answered | False -> **True** | answerable_answered_correct |
| P12-065 | answerable | M2C-14 | M2C-14 | M2C-14 | - | answered -> answered | True | answerable_answered_correct |
| P12-066 | absent_detail | M2C-07 | M2C-06 | M2C-07 | YES | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-067 | absent_detail | M2C-07 | M2C-22 | M2C-02 | YES | out_of_domain -> insufficient_context | False | LOW_QUERY_TERM_COVERAGE_IN_CONTEXT |
| P12-068 | absent_detail | M2C-07 | M2C-18 | M2C-17 | YES | out_of_domain -> insufficient_context | False | LOW_QUERY_TERM_COVERAGE_IN_CONTEXT |
| P12-069 | absent_detail | M2C-05 | M2C-09 | M2C-05 | YES | out_of_domain -> insufficient_context | False | GENERATOR_REFUSED |
| P12-070 | absent_detail | M2C-05 | M2C-05 | M2C-05 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-071 | absent_detail | M2C-24 | M2C-24 | M2C-24 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-072 | absent_detail | M2C-24 | M2C-23 | M2C-23 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-073 | absent_detail | M2C-24 | M2C-23 | M2C-24 | YES | out_of_domain -> insufficient_context | False | LOW_QUERY_TERM_COVERAGE_IN_CONTEXT |
| P12-074 | absent_detail | M2C-14 | M2C-27 | M2C-25 | YES | out_of_domain -> insufficient_context | False | GENERATOR_REFUSED |
| P12-075 | absent_detail | M2C-14 | M2C-14 | M2C-14 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-076 | absent_detail | M2C-17 | M2C-18 | M2C-17 | YES | unresolved_identity -> insufficient_context | False | GENERATOR_REFUSED |
| P12-077 | absent_detail | M2C-17 | M2C-18 | M2C-17 | YES | unresolved_identity -> insufficient_context | False | LOW_QUERY_TERM_COVERAGE_IN_CONTEXT |
| P12-078 | absent_detail | M2C-11 | M2C-16 | M2C-11 | YES | unresolved_identity -> insufficient_context | False | GENERATOR_REFUSED |
| P12-079 | absent_detail | M2C-11 | M2C-11 | M2C-11 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-080 | absent_detail | M2C-02 | M2C-25 | M2C-04 | YES | out_of_domain -> insufficient_context | False | LOW_QUERY_TERM_COVERAGE_IN_CONTEXT |
| P12-081 | absent_detail | M2C-02 | M2C-03 | M2C-03 | - | insufficient_context -> insufficient_context | False | LOW_QUERY_TERM_COVERAGE_IN_CONTEXT |
| P12-082 | not_ingested | M2C-25 | M2C-23 | M2C-23 | - | answered -> answered | False | not_ingested_incorrectly_answered |
| P12-083 | not_ingested | M2C-04 | M2C-04 | M2C-04 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-084 | not_ingested | M2C-03 | M2C-03 | M2C-03 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-085 | not_ingested | M2C-12 | M2C-12 | M2C-12 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-086 | not_ingested | M2C-08 | M2C-08 | M2C-08 | - | answered -> answered | False | not_ingested_incorrectly_answered |
| P12-087 | not_ingested | M2C-09 | M2C-09 | M2C-09 | - | answered -> answered | False | not_ingested_incorrectly_answered |
| P12-088 | not_ingested | M2C-23 | M2C-23 | M2C-23 | - | answered -> answered | False | not_ingested_incorrectly_answered |
| P12-089 | not_ingested | M2C-23 | M2C-24 | M2C-23 | YES | insufficient_context -> insufficient_context | False | LOW_QUERY_TERM_COVERAGE_IN_CONTEXT |
| P12-090 | not_ingested | M2C-26 | M2C-27 | M2C-26 | YES | insufficient_context -> answered | False | not_ingested_incorrectly_answered |
| P12-091 | not_ingested | M2C-29 | M2C-29 | M2C-29 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-092 | unresolved_identity | M2C-18 | M2C-18 | M2C-17 | YES | unresolved_identity -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-093 | unresolved_identity | M2C-18 | M2C-18 | M2C-17 | YES | unresolved_identity -> insufficient_context | False | GENERATOR_REFUSED |
| P12-094 | unresolved_identity | M2C-18 | M2C-18 | M2C-17 | YES | unresolved_identity -> insufficient_context | False | GENERATOR_REFUSED |
| P12-095 | unresolved_identity | M2C-13 | M2C-13 | M2C-15 | YES | unresolved_identity -> answered | False | unresolved_identity_incorrectly_answered |
| P12-096 | unresolved_identity | M2C-16 | M2C-14 | M2C-14 | - | insufficient_context -> insufficient_context | False | GENERATOR_REFUSED |
| P12-097 | unresolved_identity | M2C-01 | M2C-01 | M2C-03 | YES | unresolved_identity -> insufficient_context | False | GENERATOR_REFUSED |
| P12-098 | ambiguous | M2C-24 | M2C-24 | M2C-24 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-099 | ambiguous | M2C-14 | M2C-13 | M2C-14 | YES | unresolved_identity -> answered | False | ambiguous_answered_acceptable |
| P12-100 | ambiguous | M2C-17 | M2C-17 | M2C-17 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-101 | ambiguous | M2C-02 | M2C-03 | M2C-04 | YES | answered -> answered | False | ambiguous_answered_acceptable |
| P12-102 | ambiguous | M2C-07 | M2C-07 | M2C-07 | - | insufficient_context -> insufficient_context | False | GROUNDING_VERIFICATION_FAILED |
| P12-103 | ambiguous | M2C-07 | M2C-05 | M2C-05 | - | out_of_domain -> out_of_domain | False | LOW_QUERY_TERM_COVERAGE_VS_ROUTED_TOPIC |
| P12-104 | ambiguous | M2C-05 | M2C-05 | M2C-05 | - | answered -> answered | False | ambiguous_answered_acceptable |
| P12-105 | ambiguous | M2C-11 | M2C-11 | M2C-12 | YES | answered -> answered | False | ambiguous_answered_acceptable |
| P12-106 | out_of_domain | None | M2C-17 | M2C-17 | - | out_of_domain -> out_of_domain | False | LOW_QUERY_TERM_COVERAGE_VS_ROUTED_TOPIC |
| P12-107 | out_of_domain | None | M2C-26 | M2C-06 | YES | out_of_domain -> out_of_domain | False | LOW_QUERY_TERM_COVERAGE_VS_ROUTED_TOPIC |
| P12-108 | out_of_domain | None | M2C-27 | M2C-27 | - | out_of_domain -> out_of_domain | False | LOW_QUERY_TERM_COVERAGE_VS_ROUTED_TOPIC |
| P12-109 | out_of_domain | None | M2C-22 | M2C-24 | YES | out_of_domain -> insufficient_context | False | GENERATOR_REFUSED |
| P12-110 | out_of_domain | None | M2C-09 | M2C-09 | - | out_of_domain -> out_of_domain | False | LOW_QUERY_TERM_COVERAGE_VS_ROUTED_TOPIC |
| P12-111 | out_of_domain | None | M2C-04 | M2C-03 | YES | out_of_domain -> out_of_domain | False | LOW_QUERY_TERM_COVERAGE_VS_ROUTED_TOPIC |
| P12-112 | out_of_domain | None | M2C-25 | M2C-25 | - | insufficient_context -> insufficient_context | False | LOW_QUERY_TERM_COVERAGE_IN_CONTEXT |
| P12-113 | out_of_domain | None | M2C-11 | M2C-09 | YES | out_of_domain -> out_of_domain | False | LOW_QUERY_TERM_COVERAGE_VS_ROUTED_TOPIC |
