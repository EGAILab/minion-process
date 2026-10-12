#!/bin/sh
# Negative controls for acquire_npm_pinned.sh (Owner offline-replay decision, minion-agent#99 comments 5930365971 /
# 5930377491; follow-up section E). Runs on the host or in node:22.15.1-alpine; needs node and tar.
#
#   sh selftest.sh <pinned Pi package-lock.json> <typebox-1.3.7.tgz> <typebox-1.3.6.tgz> <diff-8.0.4.tgz>
#
# Each control runs the REAL helper in a subshell (it exits on failure) and asserts the expected outcome:
#   correct offline artifact          -> PASS
#   wrong tarball (another package)   -> FAIL
#   modified tarball (one byte)       -> FAIL
#   wrong version, same filename      -> FAIL
#   wrong expected digest (lockfile)  -> FAIL
#   lockfile records another version  -> FAIL
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
LOCK=$1; GOOD=$2; OLD=$3; OTHER=$4
W=$(mktemp -d)
fails=0

run() {  # run <label> <expect PASS|FAIL> <lockfile> <tgz>
  label=$1; expect=$2; lock=$3; tgz=$4
  if (TYPEBOX_TGZ=$tgz; export TYPEBOX_TGZ; . "$HERE/acquire_npm_pinned.sh";
      acquire_npm_pinned typebox 1.3.7 "$lock" "$W/dest-$label" "$W/work-$label") >"$W/$label.log" 2>&1; then
    got=PASS
  else
    got=FAIL
  fi
  if [ "$got" = "$expect" ]; then
    echo "ok   $label: $got ($(tail -1 "$W/$label.log"))"
  else
    echo "BAD  $label: expected $expect, got $got"; cat "$W/$label.log"; fails=$((fails + 1))
  fi
}

run correct-offline-artifact PASS "$LOCK" "$GOOD"

run wrong-tarball FAIL "$LOCK" "$OTHER"

node -e '
  const fs = require("fs"); const b = fs.readFileSync(process.argv[1]);
  b[100] ^= 0xff;  // flip one byte: guaranteed different bytes, same length
  fs.writeFileSync(process.argv[2], b);
' "$GOOD" "$W/modified.tgz"
cmp -s "$GOOD" "$W/modified.tgz" && { echo "BAD  control setup: modified tarball is identical"; fails=$((fails + 1)); }
run modified-tarball FAIL "$LOCK" "$W/modified.tgz"

mkdir -p "$W/samename" && cp "$OLD" "$W/samename/typebox-1.3.7.tgz"
run wrong-version-same-filename FAIL "$LOCK" "$W/samename/typebox-1.3.7.tgz"

node -e '
  const fs = require("fs"); const lock = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
  lock.packages["node_modules/typebox"].integrity = "sha512-" + Buffer.alloc(64, 7).toString("base64");
  fs.writeFileSync(process.argv[2], JSON.stringify(lock));
' "$LOCK" "$W/wrong-digest-lock.json"
run wrong-expected-digest FAIL "$W/wrong-digest-lock.json" "$GOOD"

node -e '
  const fs = require("fs"); const lock = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
  lock.packages["node_modules/typebox"].version = "1.3.6";
  fs.writeFileSync(process.argv[2], JSON.stringify(lock));
' "$LOCK" "$W/wrong-version-lock.json"
run lockfile-records-another-version FAIL "$W/wrong-version-lock.json" "$GOOD"

rm -rf "$W"
[ "$fails" -eq 0 ] && echo "selftest: all controls behaved as expected" || { echo "selftest: $fails control(s) misbehaved"; exit 1; }
