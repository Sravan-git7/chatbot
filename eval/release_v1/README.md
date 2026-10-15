# Release v1 observation and independent-review package

**NOT approved SAP gold. NOT a release-quality pass.** The ten versioned cases cover positive, negative, ambiguous, navigation-only, wrong-guide, version-conflict and insufficient-evidence situations. Positive references reuse immutable historical inputs, not newly invented SAP facts. Input SHA256 checks abort on drift; existing labels, baselines, corpus, scores and tolerances are unchanged.

From the candidate root, with the approved verification interpreter:

```sh
python eval/release_v1/verify.py --out /new/private/path/preflight.json
# Only against an explicitly approved existing private service:
python eval/release_v1/verify.py --url https://approved-private-api.example --out /new/private/path/observations.json
```

The second command is illustrative, not a deployed endpoint. Supply a gateway token through the process secret manager (`SURA_API_TOKEN`), never command-line arguments or committed files. The runner starts no server, downloads no model, creates no store and refuses output overwrites. Treat response artifacts as private.

Exit 1 means drift or conspicuous API failures; exit 2 means blocked/not independently certified. There is intentionally no automated semantic PASS. For positives, an answered response with matching guide/page identity and a reference quote is only `CANDIDATE`; abstention fails substantive correctness. Other non-answered responses require review, not automatic semantic credit. Quote/ID overlap cannot prove every answer claim, version or citation correct.

An independent SAP reviewer must verify the authoritative guide, version, page and claim-level supporting text, resolve ambiguous/negative labels and record adjudication separately. Keep the original package immutable; any approved gold must be a new version with rationale, evidence and reviewer identity. Do not rebaseline to candidate output.

Acceptance and intended-host performance targets were declared in `cases.json` before real candidate capacity measurements. Targets are not measurements or production certification. Full frozen evaluation, real models/stores, native Windows, authenticated real-browser workflows, dependency/security disposition and production rollback remain separate mandatory gates. See `../../RELEASE_GATES.md` and the five companion reports.
