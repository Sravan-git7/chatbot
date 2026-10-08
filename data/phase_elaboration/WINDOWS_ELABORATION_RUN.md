# Follow-up elaboration: running the REAL llama3.2:3b measurement on your Windows machine (`D:\chatbot`)

**Why on your machine:** the Arena sandbox cannot reach your Ollama (`127.0.0.1:11434` there is the sandbox itself, and
`ollama.com` / `registry.ollama.ai` / `huggingface.co` are unreachable, so no model can be installed either). Everything
below is a **measurement**; it changes nothing in the product and never touches the frozen benchmark, the corpus or any
sealed Phase-12/16/17/18 artifact.

**What it measures** (`scripts/evaluate_elaboration_llm.py`, additive, new file): for each of the 10 topics in
`data/phase_elaboration/elaboration_questions.json`, four arms —

| arm | what it is |
|---|---|
| `A_normal_extractive` | the normal production answer (`svc(extractive).ask(topic)`) |
| `A2_normal_llm` | the normal question on the LLM path, for reference |
| `B_elaboration_extractive_shipped` | **the shipped product behaviour** for the follow-up (`svc(extractive).ask(message, context={topic, A})`) |
| `B2_elaboration_extractive_scoped` | the same intent-aware pass, but always anchored to the topic's own page (the proposed fallback) |
| `C_generative_elaboration` | the **prototype**: an elaboration prompt over the *widened* evidence of the same page, through `EvidenceGuard` → `verify_grounding` → citation normalization, then the same-page scope gate + the novelty gate |
| `C_effective_*` | what a user would actually see for the follow-up: C when every gate passes, otherwise B2, with the reason recorded |

Nothing unverified can appear in any arm: arm C runs the real production guards, and the raw model text is written to the
report **only** for answers the guard withheld (so you can read what it tried to say).

**Prerequisites in the checkout** — `git pull origin arena/01a1064a-chatbot` brings this harness, the question set and this
runbook (commit *"Add elaboration LLM measurement harness"*). It does **not** bring the follow-up work the harness
measures: `scripts/rag_followup.py`, `scripts/rag_elaborate.py` and the `rag_service.ask` follow-up branch are still
uncommitted in the Arena workspace (deliberately outside that commit), and without them the harness cannot even import.
So, before step 2, copy these three files from the Arena workspace into `D:\chatbot`, keeping the relative paths:

| file | state |
|---|---|
| `scripts/rag_followup.py` | new (the deterministic follow-up resolver) |
| `scripts/rag_elaborate.py` | new (the intent-aware wider-evidence elaboration) |
| `scripts/rag_service.py` | modified (the scoped follow-up/elaboration branch in `ask()`) |

The harness itself (`scripts/evaluate_elaboration_llm.py`), `data/phase_elaboration/elaboration_questions.json` and this
runbook come from the pull. After copying, `git status --short` should show exactly those three files as changed/new plus
nothing unexpected; the only *new tracked* paths are `scripts/evaluate_elaboration_llm.py` and `data/phase_elaboration/`.
The harness measures; it cannot alter the product by being present.

```powershell
# 0. in D:\chatbot, on the session branch
cd D:\chatbot
git branch --show-current                  # arena/01a1064a-chatbot
git status --short                         # expect the uncommitted follow-up work + data/phase_elaboration/

# 1. Ollama answering?
ollama list                                # llama3.2:3b must be listed (the run refuses to start otherwise)
python scripts/evaluate_elaboration_llm.py --preflight
#   -> prints the environment; writes data/phase_elaboration/elaboration_environment.json
#   -> do NOT run scripts/phase12_ollama_check.py for this: it rewrites the sealed Phase-12 environment record

# 2. guard check first, without the model (validates the harness and the guard chain end to end, ~1 minute)
python scripts/evaluate_elaboration_llm.py --generator-llm stub --stub-mode all `
  --out data/phase_elaboration/stub_run.json --markdown data/phase_elaboration/stub_report.md `
  --checkpoint data/phase_elaboration/stub_run.ckpt.jsonl --environment data/phase_elaboration/stub_environment.json
#   expect: uncited / phantom / invented / refusal stub outputs are all withheld
#           (NO_CITATION / PHANTOM_MARKER / TOKEN_NOT_IN_CONTEXT / GENERATOR_REFUSED) and 0 grounding failures are shown

# 3. the real run (~10 topics x 5 arms ~= 50 model calls; a few minutes after the model is loaded)
python scripts/evaluate_elaboration_llm.py
#   -> data/phase_elaboration/elaboration_run.json   (all records + metrics)
#   -> data/phase_elaboration/elaboration_report.md  (readable report: per-topic answers of every arm)
#   -> data/phase_elaboration/elaboration_run.ckpt.jsonl (one line per finished topic; keeps partial results)
#   the sealed files under data/phase12|16|17a|18 and data/evaluation are refused as output paths

# 4. optional: the repository test suite on your machine
python -m pytest tests -q -p no:cacheprovider
```

**Send back**: `data\phase_elaboration\elaboration_report.md`, `elaboration_run.json`,
`elaboration_environment.json` and the console output of steps 1–3. Do not commit anything yet; the commit happens only
after you approve it.

**What I will read out of the run**

1. **EL-005 (the critical probe, "What is a contract account?" → "Explain why companies use it.").** Today the product
   answers it off-topic (the resolver does not recognise the message, so it runs as a standalone question and routes to
   the "Collection Agency APIs" page — reproduced in the offline run: `B` = 264 chars about collection history).
   The run shows whether the prototype refuses (rule 6 of the elaboration prompt) and, if it refuses, that the fallback is
   the page-scoped extractive elaboration of the contract-account page — or the honest "the documentation does not provide
   more detail" answer. A confident "why" invented from outside knowledge is a FAIL even though the guard may pass a
   grounded-looking sentence: judge the text, not just the counters.
2. **EL-010** ("What is clearing control?" → "Tell me more."): the page holds nothing beyond the first answer; the expected
   outcome is the shipped honest abstention, not an invented paragraph.
3. **Gate outcomes and the fallback rate** (`summary.generative_gate_outcomes`): how often the guard withholds, refuses, or
   the novelty gate fires — i.e. how often a real follow-up would silently fall back to the deterministic elaboration.
4. **Latency** (`median_generate_ms`, `median_total_ms` per arm): the price of the richer path per follow-up.
5. **Duplication** (`novelty_vs_A`, `similarity_vs_A`): an elaboration must not be the previous answer again.

**Reading the report honestly:** arm C uses a prototype prompt that lives in the evaluator, not in the product, and the
same-page/novelty gates are computed by the evaluator — so this run measures *whether the guarded LLM path can carry
elaboration*, not a finished feature. If it does not clearly beat arm B2 on correctness-without-invention and readability,
the recommendation stays "keep the extractive elaboration as the default".
