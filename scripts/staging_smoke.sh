#!/usr/bin/env bash
# SURA staging smoke — 9 representative cases against remote service via proxy
# Usage: ./scripts/staging_smoke.sh https://sura-staging.example.com [--token TOKEN]
set -euo pipefail
BASE="${1:-https://sura-staging.example.com}"
TOKEN="${2:-}"
HDR=()
if [[ -n "$TOKEN" ]]; then HDR=(-H "Authorization: Bearer $TOKEN"); fi
pass=0; fail=0
check() {
  local name="$1" q="$2" expect="$3"
  echo "== $name: $q"
  resp=$(curl -fsS "${HDR[@]}" -H "Content-Type: application/json" -H "X-Request-Id: smk-$(date +%s)-$$" \
    -d "{\"message\":$(printf '%s' "$q" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
    "$BASE/api/chat" || true)
  echo "$resp" | python3 -c "
import json,sys
j=json.load(sys.stdin)
status=j.get('status') or j.get('error',{}).get('code')
print('status',status)
# basic validation: answerable must have sources + valid doc_id format
if j.get('sources'):
  for s in j['sources']:
    assert 'doc_id' in s and '/' in s['doc_id'], 'bad doc_id'
    assert s['doc_id'].count('/')==1
print('sources',len(j.get('sources',[])))
" && pass=$((pass+1)) || { echo "FAIL $name"; fail=$((fail+1)); echo "$resp"; }
  # check expect substring
  if ! echo "$resp" | grep -q "\"status\":.*\"$expect\""; then
    echo "Expected status $expect not found"
    fail=$((fail+1))
  fi
}
echo "Health"
curl -fsS "$BASE/health" | python3 -c "import json,sys; j=json.load(sys.stdin); assert j['status']=='ok'"
echo "Ready"
curl -fsS "$BASE/ready" | python3 -c "import json,sys; j=json.load(sys.stdin); assert j.get('ready')==True, j"

check "EL43" "What is the purpose of transaction EL43?" "answered"
check "ELDM" "What does transaction ELDM display?" "answered"
check "device-number" "How is a device number created in Device Management?" "answered"
check "EL31-abstain" "What is the maximum number of meter reading orders that transaction EL31 can display?" "unable_to_verify"
# empty
echo "== empty"
curl -fsS -H "Content-Type: application/json" -d '{"message":""}' "$BASE/api/chat" | grep -q "invalid_request" && pass=$((pass+1)) || fail=$((fail+1))
check "cake-OOD" "How do I bake a chocolate cake?" "out_of_scope"
check "compare" "Compare Move-In and Move-Out" "answered"
check "followup-bare" "Explain further" "clarification"

echo "Smoke: $pass passed, $fail failed"
exit $fail
