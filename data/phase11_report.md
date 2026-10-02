# Phase 11 - RAG chat product UI and end-to-end integration

Status: **implemented and verified end to end; not committed** (waiting for approval). The product answers real questions through the real pipeline and
shows real citations. It is **not** a claim that answer quality is good: the end-to-end set below exposes the same retrieval weaknesses measured in Phase 9/10
(wrong card, extractive sentence choice, absent-detail questions answered). Those are reported, not tuned away.

## 1. What was built

| Layer | File | Role |
|---|---|---|
| Service boundary | `scripts/rag_service.py` | one stable `answer_question(...)` over the existing `rag_pipeline.RagPipeline` (no second RAG implementation); maps pipeline statuses to the public contract; hides debug data unless asked |
| API | `scripts/rag_api.py` | FastAPI + Pydantic: `GET /api/health`, `POST /api/chat`; also serves `web/dist`; explicit CORS allow-list; request limits |
| UI | `web/` | sidebar with history, welcome screen, Markdown answers, sources, status notes, error states, optional developer panel, mobile drawer |
| E2E | `scripts/phase11_e2e.py`, `web/e2e/browser_e2e.cjs` | HTTP-level run (16 questions) and a real-browser run (25 checks) against the live server |

Public response: `{answer, conversation_id, status, sources:[{title,url,source_id,type}], metadata:{card_id, identity_status, generator, grounded}}` plus
`topic_reference` (the stored URL of a topic whose page is missing, labelled "Reference only", never counted as a source). Public statuses: `answered`,
`documentation_unavailable`, `unable_to_verify`, `out_of_scope`; a generator failure is an HTTP 502 error (`generator_failed`), not an answer status. Debug data only with `{"debug": true}` and only shown behind the developer toggle.

Behaviour decisions taken from repo evidence:
* Generator is chosen at startup (`--generator extractive|ollama`); there is **no runtime fallback**. If Ollama is selected and unreachable the API returns a controlled 502 `generator_failed` error, never an extractive answer.
* The conversation is kept in the browser (local storage). The backend is stateless; `conversation_id` is only echoed/validated. Each question is answered on its own (stated in the UI).
* Loading state is one honest message ("Searching the SAP Utilities documentation and preparing an answer...") because the backend does one blocking call and reports no stages. No streaming was built (the pipeline does not stream), and no regenerate/stop button exists for the same reason.
* Citation chips in the text only exist for markers that are real sources of that answer; links in answer text are never rendered; raw HTML is dropped.

## 2. Real-answer smoke test (before the UI existed; repeated in the suite)

| Case | Result |
|---|---|
| A normal answer | answered from "Creating Installment Plans", stored help.sap.com URL preserved, grounding passed |
| B unknown / unsupported | `out_of_scope`, no sources |
| C page not ingested | `documentation_unavailable`, reference-only topic, no sources, card text not used as evidence |
| D absent detail | see failure E16 below: **not reliably abstained** |
| E generator failure (simulated by an exception in the generator) | HTTP 502 `generator_failed`, no answer text |
| F citation integrity | every URL equals the stored URL; no card cited as evidence (also checked in `tests/test_phase11_guards.py`) |

## 3. End-to-end results (`data/phase11_e2e_results.json`, 16 AI-authored questions, extractive generator, 7 of 29 pages ingested)

Question expectations were written and frozen before the run (sha256 recorded in the results). The one change made after the first run was to the
*measurement*: the "routed card" is read from the debug routing block, because the public metadata hides the card for out-of-scope answers (the first run mis-labelled E14). No expectation was edited.

**9 / 16 pass. Answerable questions: 5 / 10. Negative/abstention questions: 4 / 6.**

| Id | Question (short) | Expected | Got | Class |
|---|---|---|---|---|
| E01 E03 E05 E07 E10 | monitoring, installment plan, invoicing, billing, device mgmt | answered | answered, evidence in cited chunk, URL = stored URL | pass |
| E11 E12 | dunning, collection agency | documentation unavailable | documentation unavailable | pass |
| E13 | weather | out of scope | out of scope | pass |
| E15 | "business partner" | unable to verify | unable to verify (router picked the M2C-18 conflict card) | pass |
| E02 | What does Device Management manage? | answered with the intro sentence | answered and grounded, but with another sentence ("The following table lists ... components") | **evidence not in cited chunk** (extractive sentence selection) |
| E04 | Which transaction creates an installment plan? | answered with the transaction | answered and grounded, but with the generic "You create an installment plan when ..." lines | **evidence not in cited chunk** |
| E06 | What happens to the contract in a move-out? | answered (M2C-02 page is ingested) | router chose M2C-04 -> documentation unavailable | **routing miss** (honest, but unhelpful) |
| E08 | How is the first installment calculated? | answered (M2C-24) | router chose M2C-23 -> documentation unavailable | **routing miss** |
| E09 | What does Contract Accounts enable? | answered (M2C-17) | router chose M2C-18 -> unable to verify | **routing miss** (M2C-18 protected conflict) |
| E14 | Authorization object for EL31? | unable to verify | router chose M2C-18; out-of-domain gate answered "out of scope" | misrouted + status differs; both are honest non-answers |
| E16 | What is the minimum installment amount? | abstain (detail absent from the page) | **answered** with related installment sentences | **absent_detail_answered** - the one user-misleading failure |

Reading: no failure fabricated content, invented a citation, rewrote a URL or presented a card as evidence. Every "answered" row was grounded and cited a
stored URL. The failures are the known Phase 9/10 limits (card router R@1 0.4595 on the frozen set; extractive generator picks sentences by overlap and
cannot decide that a detail is absent). E16 is a deliberate repeat of a known weak case (P10D-048) and is not a fresh finding. Phase 11 did **not** change routing, retrieval, generation or grounding, so
these numbers are a product-level view of the existing pipeline, from a small, author-written 16-question set (no statistical claim).

Error paths (live): empty, malformed JSON, missing field, over-long message and a bad conversation id all return a controlled HTTP 422 `invalid_request`; HTML in a question is not reflected.

## 4. Browser E2E (`data/phase11/browser_e2e.json`, real Chromium, real backend): 25 / 25

Welcome and coverage line from `/api/health`; example prompt sends a real request and shows the real answer; citation URL byte-equal to the API's; links open in a new tab with `noopener`; Enter sends / Shift+Enter newline;
documentation-unavailable and out-of-scope notes; no raw `M2C-` ids outside developer mode; HTML in a question is displayed as text (no script run); new chat, history, switching, persistence across reload; developer panel off by default and showing routing/grounding/latency when on;
mobile 390x844 drawer with no horizontal overflow; network failure shows "Unable to reach the RAG service. ..."; no console errors. Screenshots: `data/phase11/screens/`.

## 5. Latency and size (this sandbox, extractive, 80 samples = 16 questions x 5)

| Measure | median | p95 |
|---|---|---|
| API round trip | 31.3 ms | 48.6 ms |
| Server total | 28.2 ms | 44.9 ms |
| Routing (card retrieval) | 17.1 ms | - |
| Page-chunk retrieval | 15.2 ms | - |
| Generation (extractive) | 0.3 ms | - |
| Health | 1.7 ms | - |

Frontend: JS 332.9 kB (104.8 kB gzip), CSS 24.1 kB (5.7 kB gzip). Browser load on localhost: DOMContentLoaded 46 ms, first contentful paint 176 ms. Local-host numbers only; an Ollama generator will dominate latency and was not measured (not available here).

## 6. Security checks

CORS explicit allow-list (no `*` with credentials); request size and id format limited; the UI renders no raw HTML (`skipHtml`, no `rehype-raw`, no `dangerouslySetInnerHTML`), drops images and Markdown links in answer text, and links only to `http(s)` URLs the backend returned
(a `javascript:` source URL is shown without a link); the extractive path cannot be steered by text in the page corpus because it only copies sentences that passed grounding; the backend adds no outbound network calls (the Phase 5 network-import scan still passes). Prompt injection against an Ollama generator was **not** tested (no Ollama).

## 7. Tests

* Python: **858 passed** (777 baseline + 25 service + 37 API + 19 guards), 0 failed, stores present. With stores absent the store-dependent tests skip as before.
* Frontend: **48 vitest tests** passed, `tsc --noEmit` clean, `vite build` OK.
* Browser: 25/25. HTTP E2E: 9/16 (reported above, not hidden).
* Bug found by the frontend tests and fixed before delivery: the Markdown preparation doubled every newline and broke tables, lists and code blocks.

## 8. Files

Created: `scripts/rag_service.py`, `scripts/rag_api.py`, `scripts/phase11_e2e.py`, `tests/test_phase11_{service,api,guards}.py`, `requirements-phase11.txt`, `web/` (source, tests, config, `package-lock.json`, `e2e/browser_e2e.cjs`, README),
`data/evaluation/phase11_e2e_questions.json`, `data/phase11_e2e_results.json`, `data/phase11/{browser_e2e.json,screens/*.png}`, `data/phase11_checkpoint.md`, this report.
Modified: **none** (no existing tracked file touched). Protected files (`rag_chat.py`, `rag_core.py`, manifests, Phase 8/9/10 queries and results, pinned tests) are unchanged: verified by the existing pinned tests and `tests/test_phase11_guards.py`.

## 9. Known limitations

1. Only 7 of 29 pages exist locally (SAP Help unreachable from this environment); most real questions end in "Documentation unavailable".
2. Extractive generator only; Ollama path is wired and tested with simulated failures but never run against a real model.
3. Card router is the bottleneck (E06/E08/E09/E14); E16 shows absent details can still be answered with related sentences. Neither was changed in Phase 11.
4. Extractive answers are copied sentences, so they can be fragmentary or miss the asked-for detail (E02, E04).
5. No streaming, regenerate or stop (pipeline is a single blocking call). No server-side conversation storage; each question is answered independently.
6. The browser E2E needs a Chromium that is not a project dependency.
7. E2E set is small and AI-authored.

## 10. Run

Backend (repo root, PowerShell): `python scripts/rag_api.py --generator extractive --host 127.0.0.1 --port 8000`
Frontend: `cd web; npm install; npm run build` then open http://127.0.0.1:8000 (or `npm run dev` for http://127.0.0.1:5173 with proxy).
