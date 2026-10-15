# Exact artifacts and known unknowns

Status: **BLOCKED / NOT PROVISIONED**, not an installation plan. Base delivery `8895a964f7ac9a4543a30073a16ce66b12f9857a`; tested functional source `29ca4ba2182b47f8452630ae5dd856ac946afe70`. [Machine-readable prerequisites](prerequisites.json) includes the complete 127-entry version reference. [delivery-inputs.sha256](delivery-inputs.sha256) pins the inherited tracked tree; no ignored/local store is thereby attested.

## 1. Embedding model and tokenizer

Required: **all-MiniLM-L6-v2**, local SentenceTransformer CPU loading, 384-dimensional normalized vectors, model maximum sequence length 256. The collection manifests declare cosine distance; page chunks use `B_heading_200` (target 200 tokens, hard cap 250 before model special tokens, min 24, overlap one sentence, embedded heading prefix). Do not substitute a similarly named model or approximate tokenizer.

The implementation in `scripts/m2c_common.py:resolve_model` considers explicit argument → `M2C_MODEL_DIR` → the third-party `gt_all_minilm_l6_v2` package's `model` directory. **There is no implemented Hugging Face cache fallback despite the docstring.** Production factory supplies no explicit model argument, so use an approved absolute `M2C_MODEL_DIR`. Avoid relying on an imported package/cache or the historical `/home/user/chatbot/.venv/lib/python3.11/site-packages/gt_all_minilm_l6_v2/model` path. `resolve_model` only checks two files for existence and records up to six hashes; a successful resolution is not complete validation.

Both tracked collection manifests agree on these SHA256 values:

| Relative file | SHA256 |
|---|---|
| `model.safetensors` | `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db` |
| `tokenizer.json` | `be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037` |
| `vocab.txt` | `07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3` |
| `config.json` | `953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41` |
| `sentence_bert_config.json` | `fc1993fde0a95c24ec6c022539d41cf6e2f7c9721e5415d6fb6897472a9cd4b7` |
| `modules.json` | `84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf` |

**Unknown:** full model export inventory and its hash, authoritative upstream revision, publisher/chain-of-custody approval and hashes for supporting files. Supply every file referenced by `modules.json` and model/tokenizer configuration, including module subdirectories such as `1_Pooling/config.json` if referenced, tokenizer configs/special-token maps and any SentenceTransformer config. A six-file-only directory is not promised loadable. Never load unapproved custom modules or remote code to fill a gap.

Known *registry metadata*, not an approved acquisition: `gt_all_minilm_l6_v2-0.1.0-py3-none-any.whl`, **83,506,384 bytes**, SHA256 **`b9a0018dff090c14865aa0996a89997e34aeadf10e400e766cb961230c58fa54`**. Its third-party repackaging is not official SAP/model-source certification. Only JSON metadata was fetched; no wheel/model was downloaded, extracted, installed or compared with the six embedded-file hashes. The source archive is an alternative distribution, not another required download. URLs/sizes/hashes are in [distribution-metadata.json](distribution-metadata.json). Approval and full exported-file verification are still required.

Runnable without model libraries **after an approved directory is supplied** (no SDK/model loading):

```sh
"$P" - <<'PY'
import hashlib, json, os
from pathlib import Path
p = Path(os.environ['M2C_MODEL_DIR'])
assert p.is_dir() and not p.is_symlink()
pins = json.loads(Path('release/evidence_closure_v3/prerequisites.json').read_text())['model']['known_files_sha256']
for name, expected in pins.items():
    f = p / name
    assert f.is_file() and not f.is_symlink(), name
    h = hashlib.sha256()
    with f.open('rb') as stream:
        for b in iter(lambda: stream.read(1024 * 1024), b''): h.update(b)
    assert h.hexdigest() == expected, name
print('Six known pins match; full-tree inventory/provenance and runtime loading still required')
PY
```

Reject junctions/reparse points, aliases and unapproved additional executable/configuration files during the **full-tree** procedure in [COLD_COPY](COLD_COPY.md); the short six-pin command alone is not a supply-chain gate.

## 2. Card and page stores — paths are fixed by current factory

`benchmarks/run_quality.py` calls `rag_service.build_service('extractive')`, which calls `rag_pipeline.build_pipeline` with `production_pipeline_config()`, local CPU embedder and owned card/page retrievers. It is **not** a generator-only cached replay. The default current stores are:

| Store | Isolated clone-relative root | Collection | Declared reference |
|---|---|---|---|
| Cards | `data/vector_store` | `sap_m2c_card_v1` | 29 vectors, dimension 384 |
| Pages | `data/vector_store/page_collection` | `sap_pages_v1` | 113 vectors, 28 pages, dimension 384 |

Those counts are pinned **manifest declarations**, not observed database contents. Read-only inspection confirms tracked `source_corpus.json` has 29 documents, `retrieval_units.json` 29 units, and page corpus manifest 28 ingested pages plus M2C-18 excluded; this makes the declared reference internally consistent, not a verified physical store. Both SQLite files are absent in the fresh clone. No original/production database has been opened.

Important identities:

- Card `source_corpus.json` file SHA256: `0ee5cb8bda192250a14acdde95617e15b71f6fd803847fe25bae9999ea7e9e76` (matches the card collection manifest).
- Card content fingerprint: `8eed668f4ac4cf951bd41df5ff94688abb7331bd05e283da1045abd1eb017cda`.
- Page corpus content fingerprint: `46e7c63af630de1a99f924320092b3bce4e29751add1eb3177b357cabd136008` (matches page collection manifest).
- Chunk fingerprint: `bc6aa3a580c5427f4c566e012c2d5390ee8025ef214d33f2c22ec2da0347281d`.
- Manifest embedding-matrix hashes: cards `0d80d10bb4e22f9311e346fd9c01b2216a2a720b08ebbb6411909c6577aecc0a`; pages `e5d148fc3e00b1e8a1f07ea3c9b649c24530c1b4f2a159c2f071d36bdce6e390`. These describe computed float32 matrices on a producer machine, **not** SQLite/HNSW byte inventories or portable equality guarantees.

**Unknown:** every SQLite/WAL/SHM/HNSW/index-file physical hash/size, snapshot ID/time, quiescence evidence, actual collection metadata/configuration, actual stored vector/content identities, producer OS/runtime and approval to use the bundle. Store owner must supply these together with matching source/retrieval/token/chunk/corpus/identity/collection manifests and signed provenance. Copy the **combined card root once**, including nested page store, to avoid mixing generations or overlapping independent copies. Include all sidecars present in the owner-approved coherent snapshot. Do not copy just `chroma.sqlite3`.

Do not create a collection to conceal missing input. Do not follow `--rebuild`, repair, refresh, normalization or installation hints in older reports/manifests/preflight. No store build is authorized here. `chroma_db/` (`sap_docs`), `av/`, backups and the original dirty checkout are **not** replacements or disposable fixtures. An owner-approved separately built replacement would need new provenance/inventories and explicit review; it is not the historical store.

## 3. Python, package and native artifacts

Reference: Linux **Python 3.11.2**, `requirements.lock.txt` (127 pinned entries including platform-marked dependencies). Key versions: Chroma 1.5.9; sentence-transformers 6.1.0; Torch 2.14.1; transformers 5.19.0; tokenizers 0.23.3; numpy 2.4.6; scipy 1.17.1; scikit-learn 1.9.1; onnxruntime 1.31.0; huggingface-hub 1.33.0; safetensors 0.8.0; ollama Python client 0.6.3; pytest 9.1.1. Full exact lines/markers remain in the unchanged lock. Its header's historical successful environment is not proof of current-suite/native compatibility.

This is a **version lock, not a wheel/hash lock**. Required owner delivery: approved interpreter binary/build/ABI/architecture, all package wheels and hashes/registry origins/license approvals, installed distribution/native shared-library inventory (including Chroma Rust bindings, Torch/BLAS/OpenMP/CPU capabilities; CUDA packages if present), OS/kernel/CPU, relevant thread/encoding/newline/locale settings and package graph. Check `pip check`/`pip freeze --all` and compare that complete approval, not only the key versions. Package install is not authorized by this document; in particular no automatic large Torch/model download or alternate Torch build.

Metadata pins, not native results:

| Chroma 1.5.9 wheel | SHA256 |
|---|---|
| `chromadb-1.5.9-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | `cc09b3df76e5a5cb386aed2715a2eea152e3949f9e1ba93c7119505377749929` |
| `chromadb-1.5.9-cp39-abi3-win_amd64.whl` | `4fd0b560e56761b7f3cb4d5c6205fd5f20814484b4a3e4e9af9038c2b428fc6c` |

Native Windows requires actual supported AMD64 Windows, explicit Python/ABI/native dependency approval and unchanged real-handle lifecycle tests. Linux-only CUDA/triton/uvloop markers do not supply that closure. Python 3.10 cannot use this Linux lock as-is; resolving ranged requirements would be a **different unverified graph**, not permission to install it now. Any upgrade for the open advisories needs fresh security review plus compatibility/regression/native/store tests before approval.

## 4. Which full evaluation, and what it does not prove

Frozen full current quality input: `data/evaluation/phase12_queries.json`, SHA256 **`3c5a9ddd2d62e9cb1919a4fbb7c81cd5239994ff230abbbe6440fb6fa5c132ac`**, 113 queries: 65 answerable, 40 negative, eight ambiguous. AI-authored frozen labels are not independent SAP gold. Current tracked page corpus is larger than the labels' original corpus; report drift separately, never relabel the frozen file.

Current production flags from `rag_service.production_pipeline_config`: top_k_cards=10, rerank_router/code_aware_router/in_page_grounding/citation_normalization/relaxed_context_gate/phrase_reranker=True, phrase_min_corroboration=2, evidence_frame_normalization/full_page_coverage/citation_repair=False; evidence guard SHIPPED_TAU=0.5, widen=False. **Do not change these to improve a score.** The strict current runner requires expected cited guide/page context plus an evidence quote in the answer; semantic truth/version/completeness still require independent review.

`evaluate_phase12.py` configurations use the pipeline's dataclass defaults and a different correctness predicate. Its optional real-Ollama full 113×real/oracle execution is supplemental historical-config evidence, **not current-production quality certification**. The current strict runner explicitly uses **extractive** generation and has no `--generator ollama` flag. Full current-production real-model semantic coverage requires separately approved current-production request replay/evidence (with actual configured generator/digest); neither the supplemental evaluator nor the five-workflow HTTP smoke supplies that gate.

## 5. Real Ollama, frontend/browser, infrastructure and SAP inputs

- Default local model **`llama3.2:3b`**, options temperature=0, seed=42. `OLLAMA_MODEL` overrides the service client's model; `OLLAMA_HOST` configures the Ollama client. Set both explicitly for an approved local daemon. Actual daemon version, executable hash, model digest/quantization/blob hashes, license and capacity approval are **unknown**. A tag is mutable and insufficient. Supply already-present approved artifacts; no `ollama pull` is authorized.
- `live_smoke.py --generator ollama` starts a private loopback service and checks five workflows, errors, served HTML and debug denial. Therefore supply a production frontend build from the unchanged `web/package-lock.json`, approved installed Node/npm frontend graph and **`web/dist`** artifact inventory too. No browser/daemon/build download was made for this package.
- Real browser/IAM/accessibility gate additionally needs an installed supported Playwright browser binary/hash, private gateway/session/ACL fixtures, two distinct principals and approved secret delivery outside reports. jsdom/build/local smoke are not authenticated-ingress evidence.
- Authoritative SAP exports and independent review are specified in [SAP_REVIEW](SAP_REVIEW.md); model/store/source file hashes alone do not verify a product release/version.
- Intended private host capacity, listener/process/SBOM/config graph, known-good deployed rollback release, compatible cold backups and explicit approvals remain absent; see [PRIVATE_REHEARSAL](PRIVATE_REHEARSAL.md).
