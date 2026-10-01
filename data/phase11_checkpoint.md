# Phase 11 checkpoint (starting state, written before any Phase 11 file)

| Item | Value |
|---|---|
| Branch | `arena/01a0ed60-chatbot` |
| HEAD at start | `bb61544252d7338704e0c281e8f76f769af84b4c` (Phase 10; = `origin/arena/01a0ed60-chatbot`) |
| History | `d85c31e` (main, untouched) → `30bbc95` (P8) → `59a766c` (P9) → `bb61544` (P10) |
| PR #1 | OPEN, mergeable, head `bb61544`, not merged |
| Working tree at start | clean after the ref repair below |
| Test count at start | 777 passed (stores present); 731 passed + 46 skipped (stores absent); 0 failed |

**Ref repair (no reset/clean/checkout):** on entering this session the sandbox had the branch ref at `d85c31e` while the working tree held the Phase 10 files
(`git status` showed 136 entries). Repaired exactly as in earlier turns: `git fetch origin`, `git update-ref refs/heads/arena/01a0ed60-chatbot bb61544… d85c31e…`,
`git read-tree bb61544`. Nothing was discarded; `git status` was clean afterwards. The virtualenv and the git-ignored vector stores had also vanished and were rebuilt
(`build_card_collection.py` / `build_page_collection.py --rebuild`, both with `--manifest /tmp/...` so the protected default manifests stay untouched).

## Existing entry points (unchanged by Phase 11)
* `scripts/rag_pipeline.py` — `build_pipeline(generator)`, `RagPipeline.answer(query, debug, oracle_source_id)` → structured answer (schema 8.1).
* `scripts/rag_answer.py` — CLI around the pipeline (`--generator extractive|ollama`; exit 2 cannot start, exit 3 generation failed).
* `scripts/rag_optimised.py` — opt-in Phase 10 experiments (not adopted; not imported by the default runtime).
* `scripts/rag_chat.py`, `rag_modes.py` — legacy / Phase 7 modes, byte-pinned.

## Protected files (must stay byte-identical)
`scripts/rag_chat.py` `e862ce38…`, `scripts/rag_core.py` `881316e4…`, `data/evaluation/phase8_results.json` `735f7061…`, `data/source_manifest.json` `08ad208c…`,
`data/card_collection_manifest.json` `5b3a5c30…`, `data/m2c_page_identity.json` `fccb0bb8…`, the 222 hashes in `data/phase7_checkpoint.md`, `.gitignore`, all
Phase 7–10 frozen query/result files (`phase8_*`, `phase9_*`, `phase10_*`), and `tests/test_phase7*.py`, `test_phase8_*`, `test_phase9.py`, `test_phase10.py`.

## Known limitations carried into Phase 11
* Corpus 7/29 pages (help.sap.com TLS is dropped from this sandbox); the other 22 topics can only answer "documentation unavailable".
* Ollama is not installed and its weights cannot be downloaded: the only generator that can run here is the deterministic extractive one. No LLM metric exists.
* Router top-1 on answerable queries is ~0.33–0.46 (Phase 9); fusion/abstention candidates from Phase 10 were NOT adopted.
* The pipeline is single-turn: there is no conversational memory.
