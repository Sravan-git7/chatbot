# Approved acquisition and cold-copy chain of custody

**Procedure only — NOT EXECUTED.** No production access, overwrite, install, large download, SDK inspection, repair or activation is authorized. Store/model/runtime suppliers and security must approve artifacts and the private target **before** import/loading. Credentials stay in approved secret delivery, never chat/argv/report URLs.

## Acquisition boundaries

1. Runtime/model owner nominates an already-present export or proposes an exact artifact URL/digest/size/platform/license/upstream revision and destination for explicit approval. Registry JSON in [distribution-metadata.json](distribution-metadata.json) is a candidate provenance anchor, not permission to download or install. Prefer an approved existing artifact mirror/wheelhouse. No automatic model/Torch downloads; no `pip install`, `ollama pull`, Hugging Face fetch or browser download in this package.
2. Supplier provides a signed approval/attestation, complete regular-file path→size→SHA256 inventory, acquisition origin/time, package/upstream version/revision, dependency/native graph, producer identity and permitted use. Verify signature against the organization's independently trusted key/channel; a checksum shipped with untrusted content is not authentication. No personal credentials need be supplied to this agent.
3. Export supporting model files as materialized ordinary files, with no symlink/junction/custom-code surprise. Compare the complete exported inventory and six known pins before any model import. A registry wheel hash alone does not prove its extracted model files match the existing collection.
4. Existing runtime acquisition/installation, if eventually approved, happens in a new isolated environment only; supply offline hash-pinned artifacts. Do not alter the preserved checkout's `av/`, caches, venvs, backups or stores. No alternate Torch/upgrade to hide gaps. Check graph/platform compatibility and advisory containment before testing.

## Store owner preconditions — cannot be established by checksums alone

- Owner must attest that the supplied tree is an **approved coherent cold snapshot**, not a live application directory. Prefer an owner-created filesystem snapshot exported read-only, or a cleanly stopped private source held under an exclusive no-writer lease from before first inventory through final source comparison. The owner, not this agent, controls any production shutdown/snapshot approval.
- Stop/verify **all** writers/readers capable of mutating/opening storage (application workers, SDK clients, Chroma processes, background jobs). Filesystem read-only protection is required for the supplied snapshot; quiescence must cover both card and nested page stores at the same generation. A before/after identical hash does **not** prove absence of concurrent writes or transient drift; retain owner/process/snapshot attestations too.
- Full bundle includes `vector_store/chroma.sqlite3`, `vector_store/page_collection/chroma.sqlite3`, every SQLite sidecar present (`-wal`, `-shm`, journal), every HNSW UUID directory/index/vector/metadata file and all other files. Do not omit sidecars or run checkpoint/VACUUM/repair during transfer. Unexpected/incoherent leftovers require owner review and abort, not deletion.
- Supplier must bind full byte inventory to current collection/corpus/chunk/model manifests, producer runtime and snapshot ID/time. [ARTIFACTS](ARTIFACTS.md) lists known logical fingerprints. **Physical store hashes are not known in this repository.** Missing producer proof remains BLOCKED even if a copy hashes correctly.
- Reject symlinks, Windows junctions/reparse points, special files, unapproved mounts/aliases and externally linked writable files. No path may alias a production/original tree. Obtain a regular-file export from the owner instead of following links. Do not open untrusted SQLite/SDK configuration to discover provenance.

## Transfer layout and non-overwrite rules

Use a **new private test clone** of `arena/b450cda2-chatbot`, with runtime bytes matching tested `29ca4ba…` / published `8895a96…`; package-only documentation commits are permissible with verified runtime equality. Materialize exact Git blob bytes without automatic newline conversion (for a newly approved Windows clone, `git clone --config core.autocrlf=false --single-branch --branch arena/b450cda2-chatbot https://github.com/Sravan-git7/chatbot.git <new-unused-private-directory>`). This does not change global Git settings or fix the sealed producer's native-newline behavior: original byte assertions still run unchanged. Do not reset/clean/normalize an existing checkout. `data/vector_store` must not exist; if it does, stop and choose another new clone. The application does not implement a generic store-path environment override.

Use three disjoint trees on a private host:

- `ColdExport`: approved read-only snapshot bundle whose root is the combined card `vector_store` (includes `page_collection`). Never point at the original checkout or a live store.
- `SealedCopy`: **new** offline backup/staging root outside the clone; after verification storage owner enforces immutable/read-only retention. Never open this through Chroma.
- `RunCopy`: **new** disposable writable clone path `<TestRoot>/data/vector_store`; only this may be opened by runtime/diagnostics. No hardlinking or shared volumes with originals/sealed copy. Each new experiment restores another fresh owned test root from sealed bytes.

Keep inventories/results **outside all three trees**. Do not copy card and page roots independently over one another: the page store is nested in the card root. Default copy operations must fail on existing destinations, not merge/overwrite. Preserve directory trees and file contents; restore attempts never erase or replace either previous tree.

## Exact standard-library byte inventory / copy recipe

Only after the above approvals and owner quiescence/snapshot attestation. `OwnerInventory` is trusted/signed JSON with schema `{"files": {"relative/posix/path": {"bytes": integer, "sha256": "hex"}}}`. It covers **all** files in `ColdExport`, including nested page store. Its own signed identity is recorded outside the tree. Storage owner can use the `inventory()` routine below to produce the unsigned measurement, then sign/approve it through their normal process; that measurement alone is not approval.

Set explicit absolute `ColdExport`, `SealedCopy`, `RunCopy`, `OwnerInventory`, `CopyEvidence` and `TestRoot` paths. `CopyEvidence` must be new. Run on an approved existing Python interpreter (`P`); this invokes **no Chroma, SQLite or model API**:

```sh
"$P" - "$ColdExport" "$SealedCopy" "$RunCopy" "$OwnerInventory" "$CopyEvidence" "$TestRoot" <<'PY'
import hashlib, json, os, shutil, stat, sys
from pathlib import Path
raw = list(map(Path, sys.argv[1:]))
for p in raw:
    assert p.is_absolute(), 'Use explicit absolute approved paths'
for p in [raw[1], raw[2], raw[4]]:
    assert not os.path.lexists(p), ('Destination already exists, including dangling link', p)
# Resolve only after rejecting the source root itself as a link/reparse point.
def regular_entry(p):
    s = p.lstat()
    assert not p.is_symlink(), p
    assert not getattr(s, 'st_file_attributes', 0) & 0x400, p  # Windows reparse point
    assert stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode), p
    if stat.S_ISREG(s.st_mode): assert s.st_nlink == 1, ('hard-linked file', p)
    return s
regular_entry(raw[0])
src, sealed, run, owner, evidence, testroot = [p.resolve() for p in raw]
assert run == testroot / 'data/vector_store'
for a in [src, sealed, run]:
    for b in [src, sealed, run]:
        if a != b: assert a not in b.parents and b not in a.parents
assert len({src, sealed, run}) == 3
for p in [sealed, run, evidence]:
    assert not os.path.lexists(p), ('Destination already exists; abort', p)
for p in [owner, evidence]:
    for tree in [src, sealed, run]: assert p != tree and tree not in p.parents
assert (src / 'chroma.sqlite3').is_file()
assert (src / 'page_collection/chroma.sqlite3').is_file()

def inventory(tree):
    regular_entry(tree)
    result = {}
    for p in sorted(tree.rglob('*')):
        before = regular_entry(p)
        if not stat.S_ISREG(before.st_mode): continue
        h = hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
        after = p.lstat()
        assert (before.st_size, before.st_mtime_ns, before.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino), ('Source drift', p)
        result[p.relative_to(tree).as_posix()] = {'bytes': after.st_size, 'sha256': h.hexdigest()}
    return result

expected = json.loads(owner.read_text())['files']
before = inventory(src)
assert before == expected, 'Signed owner inventory does not match; abort'
shutil.copytree(src, sealed)  # dirs_exist_ok defaults False; never merge
assert inventory(sealed) == expected
shutil.copytree(sealed, run)  # independent file copies, never hardlinks
assert inventory(run) == expected
assert inventory(src) == before, 'Source drift; do not certify either copy'
# No SDK use has occurred. Storage operator now seals SealedCopy read-only.
with evidence.open('x') as f:
    json.dump({'status': 'BYTE_COPY_VERIFIED_NOT_RUNTIME_PASS',
               'source': str(src), 'sealed': str(sealed), 'run': str(run),
               'owner_inventory_sha256': hashlib.sha256(owner.read_bytes()).hexdigest(),
               'files': expected}, f, indent=2)
    f.write('\n')
print('Byte copies verified. Owner attestation, storage sealing and runtime/security gates still required.')
PY
```

The infrastructure owner must independently approve/verify actual resolved paths, parent components/mounts/ACLs and exclusive lease; this snippet cannot certify those or make a live source safe. On any exception/nonzero exit: **abort**; retain partial owned destinations as failed evidence, do not automatically delete, merge or rerun over them. Choose new empty paths only after owner review. Unexpected reparse points/hardlinks must be corrected by a new approved supplier export, never by modifying the source.

After every test/rehearsal, recompute the sealed/source full inventory under the same ownership controls and compare with signed owner inventory; only the disposable run tree is expected to change after Chroma opens it. A modified run copy is not a valid pristine input for the next experiment. No test/diagnostic may open `ColdExport`, `SealedCopy`, a live store, or the original checkout through Chroma. Do **not** read untrusted SDK `.configuration` as a passive inspection step: it can reconstruct providers. Keep all original bytes and historical artifacts unchanged.
