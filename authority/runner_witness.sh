#!/bin/sh
# PROC-AUTHDEP-R001 real-runner witness: coherent pin substitution must be refused BEFORE authority execution.
#
#   PYTHON=<python3> sh runner_witness.sh <pinned Pi checkout> <runner .sh> <package> <version> <correct tarball>
#   e.g. sh runner_witness.sh ref-repos/pi assurance/layers/data/l0506-d002/harness/run_authority.sh \
#            typebox 1.3.7 .tmp/replay/typebox-1.3.7.tgz
#
# In a disposable shared clone of the pinned Pi commit (the real checkout is never touched):
#   attack:   the tarball is MODIFIED (512 zero bytes appended -- still a valid gzip of the same package) and the
#             clone's WORKING-TREE package-lock.json is coherently rewritten to that tarball's SHA-512
#             -> the unchanged committed runner must FAIL at dependency verification, with NO authority output
#   control:  the clone restored to the pinned blob + the correct tarball -> the same runner must PASS
set -u
PIN=b7bb00b936dbe21b8e160b3e89efdec361846699
PI=$(cd "$1" && pwd); RUNNER=$(cd "$(dirname "$2")" && pwd)/$(basename "$2"); PKG=$3; VER=$4
GOOD=$(cd "$(dirname "$5")" && pwd)/$(basename "$5")
W=$(mktemp -d)
VAR=$(printf '%s' "$PKG" | tr 'a-z-' 'A-Z_')_TGZ
fails=0

git clone -q --shared --no-checkout "$PI" "$W/pi" && git -C "$W/pi" checkout -q "$PIN" || { echo "clone failed"; exit 1; }

node -e '
  const fs = require("fs"); const crypto = require("crypto");
  const bytes = Buffer.concat([fs.readFileSync(process.argv[1]), Buffer.alloc(512)]);
  fs.writeFileSync(process.argv[2], bytes);
  const sri = "sha512-" + crypto.createHash("sha512").update(bytes).digest("base64");
  const lockPath = process.argv[3] + "/package-lock.json";
  const lock = JSON.parse(fs.readFileSync(lockPath, "utf8"));
  lock.packages["node_modules/" + process.argv[4]].integrity = sri;
  fs.writeFileSync(lockPath, JSON.stringify(lock, null, "\t") + "\n");
  console.log("coherent forged pin: " + sri);
' "$GOOD" "$W/modified.tgz" "$W/pi" "$PKG"
[ -n "$(git -C "$W/pi" status --porcelain -- package-lock.json)" ] || { echo "BAD setup: lockfile not modified"; fails=$((fails + 1)); }
[ -z "$(git -C "$W/pi" status --porcelain -- packages)" ] || { echo "BAD setup: packages/ dirty"; fails=$((fails + 1)); }

run() {  # run <label> <expect PASS|FAIL> <tarball>
  mkdir -p "$W/out-$1"
  if env "$VAR=$3" PI_DIR="$W/pi" OUT_DIR="$W/out-$1" STAGE_DIR="$W/stage-$1" sh "$RUNNER" >"$W/$1.log" 2>&1; then
    got=PASS
  else
    got=FAIL
  fi
  outputs=$(find "$W/out-$1" -name '*.json' ! -name 'cases.sha256' | wc -l | tr -d ' ')
  if [ "$got" = "$2" ]; then
    echo "ok   $1: $got (authority json outputs: $outputs) $(grep -E 'FAIL|verified' "$W/$1.log" | tail -1)"
  else
    echo "BAD  $1: expected $2, got $got"; tail -5 "$W/$1.log"; fails=$((fails + 1))
  fi
  if [ "$2" = FAIL ] && [ "$outputs" != 0 ]; then echo "BAD  $1: authority produced output before refusal"; fails=$((fails + 1)); fi
}

run coherent-pin-substitution FAIL "$W/modified.tgz"
git -C "$W/pi" checkout -q -- package-lock.json
run correct-artifact-pinned-blob PASS "$GOOD"

rm -rf "$W"
[ "$fails" -eq 0 ] && echo "runner witness: all controls behaved as expected" || { echo "runner witness: $fails misbehaved"; exit 1; }
