# Phase 7G - the legacy / route_only mode boundary

**Result:** a small, additive entry point `scripts/rag_modes.py` with `--mode legacy` (default) and `--mode route_only`. `rag_chat.py` and every other existing file are untouched. `route_only` runs query → card router → identity → citation metadata, and nothing more. There is no LLM, no answer, no network, no page text and no threshold.

## 1. State recorded before any change

| Item | Value |
|---|---|
| HEAD | `d85c31e0594b472e852ea9e06e32e6eba7138747` on `arena/01a0ed60-chatbot` |
| Tracked files modified | 9, unchanged since before Phase 7 (`.gitignore`, `data/retrieval_results.json`, `scripts/{audit_corpus,chunk_pages,clean_sap_pages,create_embeddings,evaluate_retrieval,rag_chat,retrieve}.py`) |
| Untracked entries | 95 (Phases 1-7F) |
| Suite (store rebuilt) | **497 passed, 0 skipped, 0 failed** |
| `data/card_collection_manifest.json` | `5b3a5c30…` |
| `scripts/rag_chat.py` / `scripts/rag_core.py` | `e862ce38…` / `881316e4…` (recorded in the 7A checkpoint) |

The checkpoint's 222 hashes are enforced by the existing 7A test, which still passes. The sandbox reset once during the session and dropped `/tmp` and the store. The "before" figures above come from the test run and the pinned hashes. I rebuilt the venv and the store with the 7B/7E procedure (manifest written to `/tmp`).

## 2. What the spec says, and what I did

Spec 7G: "One commit adding `--mode` to `rag_chat.py`, default `legacy`", delegating to the orchestrator. The spec's four modes are `legacy`, `shadow`, `routed`, `route_only`.

I checked the repository first. Editing `rag_chat.py` would break the checkpoint hash and about six older guard tests, which assert that `rag_chat.py` never mentions the new modules. You said not to change old expectations, so I asked. **You chose a separate entry point and left `rag_chat.py` byte-identical.** You also chose to reject `shadow` and `routed`, because they need an LLM answer.

| Mode | Behaviour |
|---|---|
| `legacy` (default) | Calls the existing `rag_chat.main()` with no arguments. Imported only inside `run_legacy()`. |
| `route_only` | Card router → `route_to_page` → identity → `cite_outcome`. Prints or returns the closest card, its URL, review flags, identity status and both similarity and distance. |
| `shadow`, `routed` | Rejected: "specified but not implemented: needs an LLM answer over SAP page chunks, and there is no page corpus or answer pipeline yet". No alias, no fallback. |
| anything else | `unknown mode … Valid modes: legacy, route_only`. Exit code 2. Matching is exact and case-sensitive. |

Your task text sketched the routing path under the name `routed`. In the spec, `routed` is the LLM soft-boost mode and the metadata-only mode is `route_only`, so I used the spec's name. Aliasing `routed` would have made a metadata mode look like an answer mode.

## 3. CLI

```powershell
# legacy: default, identical to `python scripts/rag_chat.py`
python scripts/rag_modes.py
python scripts/rag_modes.py --mode legacy

# route_only: one question
python scripts/rag_modes.py --mode route_only --question "How are dunning notices created?"
python scripts/rag_modes.py --mode route_only --question "How are dunning notices created?" --top-k 3 --json

# route_only: interactive (type exit to quit)
python scripts/rag_modes.py --mode route_only

# rejected, exit code 2
python scripts/rag_modes.py --mode routed
python scripts/rag_modes.py --mode bogus
python scripts/rag_modes.py --question "x"      # --question/--top-k/--json need --mode route_only
```

`route_only` needs `data/vector_store` and the local model. If the store is missing it prints `Error (router_unavailable): …` and exits 2. It never falls back to legacy.

Real output (shortened):

```
Closest topic card: FI-CA Dunning (source: https://help.sap.com/docs/.../b1ffc5536a51204be10000000a174cb4.html). The page content is not available locally.
1. FI-CA Dunning (M2C-26) | similarity=0.4837 | distance=0.5163
Rank, not confidence: no similarity threshold is applied (Phase 7F found no justified threshold), ...
Sources (card route only: topic identification; no page text; no model involved):
1. [card_route] FI-CA Dunning (M2C-26) | identity=identified_not_local
```

For "What is the weather today?" it still returns Meter Reading Estimation with similarity 0.0416. That is the 7F finding, shown as rank and score and not as an answer.

## 4. Guarantees, and how each is tested (`tests/test_phase7g.py`, 43 tests)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Default is legacy | `DEFAULT_MODE == "legacy"`. `main([])` calls `rag_chat.main()` once and does not touch the router. A fresh-process test uses the real `rag_chat` with only `main` patched. |
| 2 | Explicit mode works | `--mode route_only` routes and never calls `rag_chat`. Covers JSON, the interactive loop and blank lines. |
| 3 | Invalid mode fails clearly | 7 bad spellings, `shadow` and `routed`: exit 2 and a message. Legacy mode with route_only options is an error. A missing store is `router_unavailable`. |
| 4 | No silent legacy | A fake `rag_chat` is never called in route_only. AST: `rag_chat` is imported only inside `run_legacy`. A subprocess shows `rag_chat`, `rag_core`, `retrieve`, `ollama`, `requests`, `chromadb` and `torch` not loaded. |
| 5 | No LLM | AST and vocabulary scan. The payload says `llm_called: false` and `answer_generated: false`. |
| 6 | No network | AST bans `socket` and `requests`. Socket connect is patched to fail, with 0 attempts. The live end-to-end run also blocks sockets. |
| 7 | No threshold | `MIN_COSINE is None`. There is no threshold parameter or option, and the parser's option set is pinned. A card at similarity 0.01 is still selected, flagged "Rank, not confidence". |
| 8 | No URL rewritten | For all 29 cards, the selected URL, the citation URL, the 7D audit URL and the `units.json` URL are byte-identical. |
| 9 | Identity unchanged | All 29 statuses match: 1 `resolved_local_page` (M2C-17), 23 `identified_not_local`, 1 `corrected_identity` (M2C-05), 3 `card_identity_only` (M2C-01, 13, 16), 1 `conflicting_identity` (M2C-18), 0 unresolved. Review flags are on M2C-14, 18 and 23 only. Status, flag, reasons and citation equal the 7D audit. |
| 10 | Citation semantics unchanged | Every source is `origin: card_route`, with `used_as_answer_text`, `provided_as_context` and `verified_used` all false. There is never a `page_chunk` source. M2C-17 says "A local page record exists … does not retrieve or use page text" (`page_text_used: false`). All other cards say "not available locally". `resolved_page` and `url_only` stay distinct. |
| 11 | Phase 4/5 unchanged | Live: the top-5 of all 50 Phase 4 queries equals the recorded rankings through `route_only`. The top-5 of all 54 Phase 5 queries equals the 7E rankings. Order is preserved exactly, and the store content is unchanged after routing. |
| 12 | Old tests unchanged | Hash-pins for the 7A-7F test files, `test_phase5.py`, `rag_chat.py`, `rag_core.py`, `retrieve.py`, `evaluate_retrieval.py`, `create_embeddings.py`, the 7E/7F evaluators and results, the router and orchestrator, the collection manifest, the checkpoint and the 7D/7C artefacts. |

## 5. Suite results

| Condition | Result |
|---|---|
| Baseline before 7G (store rebuilt) | 497 passed, 0 skipped |
| **After 7G, store rebuilt** | **540 passed, 0 skipped, 0 failed** (497 + 43 new) |
| After 7G, store absent | 508 passed, 32 skipped, 0 failed |

The 32 skips without the store are store-gated tests: 28 from earlier phases plus 4 in 7G (Phase 4 and Phase 5 live top-5, the real end-to-end CLI run, the store-unchanged check).

## 6. Files

- **Created (3):** `scripts/rag_modes.py`, `tests/test_phase7g.py`, `data/phase7G_report.md`.
- **Modified:** none. The same 9 tracked files remain modified as before 7G, and their content is unchanged.
- **Untouched:** everything else. This includes `rag_chat.py`, `rag_core.py`, `retrieve.py`, `evaluate_retrieval.py`, `create_embeddings.py`, `m2c_router.py`, `m2c_page_join.py`, `m2c_page_identity.py`, `m2c_orchestrator.py`, `m2c_citations.py`, `evaluate_two_stage.py`, `evaluate_ood.py`, `data/card_collection_manifest.json`, `retrieval_units.json`, all evaluation data and all old tests.
- **Protected hashes changed:** none. The manifest is `5b3a5c30…`, and the checkpoint test passes.
- **Network / LLM:** none at runtime. `pip` (PyPI) was used only to rebuild the sandbox venv. No SAP page was fetched and no Ollama call was made.
- **Not created:** no `chroma_db`, no page chunks, no page embeddings, no new vector store, no `__pycache__`.

## 7. Deviations to know about

1. **Entry point:** `scripts/rag_modes.py`, not `rag_chat.py --mode`. This follows your choice, and `rag_chat.py` is byte-identical.
2. **Module name:** the spec calls the orchestrator `rag_two_stage.py`. I did not use that name. The 7F test asserts that file does not exist, and you asked for no old-test edits. In my question to you I said the spec's name could be used with no old test changes, which was wrong, because of that one assertion. Renaming later is a one-line change plus that assertion.
3. **Wording:** the spec's text is "This topic is covered by …". I wrote "Closest topic card: …", because 7F showed rank 1 is not evidence of coverage.
4. **Citation heading:** 7D's label says "Sources provided to the model". Nothing is given to a model in `route_only`, so the text output uses its own heading. The JSON keeps 7D's label unchanged.
5. **Legacy mode not run live:** it needs Ollama and `chroma_db`, which don't exist here. It is tested as pure delegation to the real `rag_chat.main`, patched.

## 8. Unresolved and not started

- `shadow` and `routed` are specified and not implemented. They need the page corpus and answer generation.
- Only M2C-17 has local page text, and `route_only` does not use it.
- 7F's finding stands: rank 1 is not a confidence, and out-of-domain questions still receive a card.
- If you want `rag_chat.py --mode`, it's a small follow-up: call `rag_modes.main` from `rag_chat.py`. It requires changing the 7A checkpoint hash and the guard tests that say `rag_chat.py` is untouched. I didn't do it.
- Nothing is committed or pushed. `.git` state has been lost between sessions before, so commit and push soon.
- Phase 8 (page acquisition, chunking, embeddings, answers, UI) is not started.
