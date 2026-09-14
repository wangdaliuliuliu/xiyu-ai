#!/usr/bin/env bash
set -Eeuo pipefail

# Acceptance tests for the release verifier. They only unpack into /tmp and
# intentionally exercise failure paths; they never call systemd or production.
ZIP_PATH="${1:?usage: agency_release_verify_negative_smoke.sh RELEASE_ZIP}"
ROOT="$(mktemp -d /tmp/xiyu-release-verify-negative.XXXXXX)"
trap 'rm -rf -- "$ROOT"' EXIT

GOOD="$ROOT/good"
BAD_BUNDLE="$ROOT/bad-bundle"
mkdir -p "$GOOD" "$BAD_BUNDLE"
unzip -q -- "$ZIP_PATH" -d "$GOOD"
unzip -q -- "$ZIP_PATH" -d "$BAD_BUNDLE"

good_stdout="$ROOT/good.stdout"
good_stderr="$ROOT/good.stderr"
set +e
(cd /tmp && XIYU_RELEASE_VERIFY_ONLY=1 XIYU_RELEASE_BUNDLE_ONLY=1 bash -u "$GOOD/apply-concern-production.sh") >"$good_stdout" 2>"$good_stderr"
good_status=$?
set -e
test "$good_status" -eq 0
test ! -s "$good_stderr"
grep -q 'bundle verification passed: 13 payload files' "$good_stdout"
if grep -q 'verify_only=passed' "$good_stdout"; then
  echo 'bundle-only verifier emitted full verify-only conclusion unexpectedly' >&2
  exit 1
fi

printf '\nintentional payload corruption\n' >> "$BAD_BUNDLE/payload/package.json"
bad_stdout="$ROOT/bad.stdout"
bad_stderr="$ROOT/bad.stderr"
set +e
(cd /tmp && XIYU_RELEASE_VERIFY_ONLY=1 XIYU_RELEASE_BUNDLE_ONLY=1 bash -u "$BAD_BUNDLE/apply-concern-production.sh") >"$bad_stdout" 2>"$bad_stderr"
bad_status=$?
set -e
test "$bad_status" -ne 0
if grep -Eq 'bundle verification passed|verify_only=passed' "$bad_stdout" "$bad_stderr"; then
  echo 'corrupt bundle produced a passed conclusion' >&2
  exit 1
fi

node_stdout="$ROOT/node.stdout"
node_stderr="$ROOT/node.stderr"
set +e
ENTRY_FILE="$ROOT/missing-entry.mjs" PROJECT_ROOT="$ROOT" node "$GOOD/payload/scripts/agency_release_static_closure.mjs" >"$node_stdout" 2>"$node_stderr"
node_status=$?
set -e
test "$node_status" -ne 0
if grep -q 'static_import_closure=' "$node_stdout" "$node_stderr"; then
  echo 'failed static-closure node check produced a passed conclusion' >&2
  exit 1
fi

printf '%s\n' '{"status":"passed","scenario":"release_verify_positive_and_negative","positiveStderrBytes":0,"corruptBundleExitNonzero":true,"nodeFailureExitNonzero":true,"passedFalsePositive":false}'
