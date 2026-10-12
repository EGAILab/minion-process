# Pinned external authority dependency acquisition (process/authority-dependencies.md). POSIX sh; source it, then
#   acquire_npm_pinned <package> <version> <pinned package-lock.json> <destination node_modules/<package> dir> <work dir>
#
# ONE verification path for both sources:
#   offline  <PACKAGE>_TGZ=/path/<package>-<version>.tgz   (e.g. TYPEBOX_TGZ, DIFF_TGZ) -- explicitly supplied bytes
#   network  npm pack <package>@<version>                   (convenience fallback when the variable is unset)
# Whatever the source, the bytes are verified against the AUTHORITATIVE pin before anything is unpacked:
#   1. the pinned lockfile's packages["node_modules/<package>"] records exactly <version> and an sha512 integrity
#   2. the supplied/downloaded tarball's SHA-512 equals that integrity (computed here, never taken from the supplier)
#   3. exactly those bytes are unpacked, and the unpacked package.json declares <version>
# Any failure is fatal (die). The caller then runs the SAME authority whichever source supplied the bytes.
#
# The canonical copy is process/tools/authority/acquire_npm_pinned.sh in minion-agent-docs; each evidence harness
# carries a byte-identical copy so the evidence directory stays self-contained for its container mount
# (process/tools/tests/test_authority_dependencies.py enforces the copies are identical).

_pinned_die() { echo "FAIL: $*" >&2; exit 1; }

acquire_npm_pinned() {
  _name=$1; _version=$2; _lock=$3; _dest=$4; _work=$5
  [ -f "$_lock" ] || _pinned_die "no pinned lockfile at $_lock"
  _pin=$(node -e '
    const lock = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"));
    const entry = (lock.packages || {})["node_modules/" + process.argv[2]] || {};
    process.stdout.write((entry.version || "") + " " + (entry.integrity || ""));
  ' "$_lock" "$_name")
  _pin_version=${_pin%% *}
  _sri=${_pin#* }
  [ "$_pin_version" = "$_version" ] || _pinned_die "pinned lockfile records $_name@$_pin_version, not $_version"
  case "$_sri" in sha512-?*) ;; *) _pinned_die "pinned lockfile has no sha512 integrity for $_name" ;; esac

  _var=$(printf '%s' "$_name" | tr 'a-z-' 'A-Z_')_TGZ
  eval "_supplied=\${$_var:-}"
  mkdir -p "$_work"
  if [ -n "$_supplied" ]; then
    [ -f "$_supplied" ] || _pinned_die "$_var=$_supplied does not exist"
    _tgz=$_supplied
    echo "== $_name@$_version: OFFLINE artifact $_tgz (untrusted until verified)"
  else
    (cd "$_work" && npm pack --silent "$_name@$_version" >/dev/null) || _pinned_die "npm pack $_name@$_version"
    _tgz=$_work/$_name-$_version.tgz
    echo "== $_name@$_version: NETWORK npm pack (untrusted until verified)"
  fi

  _got="sha512-$(node -e 'process.stdout.write(require("crypto").createHash("sha512").update(require("fs").readFileSync(process.argv[1])).digest("base64"))' "$_tgz")"
  [ "$_got" = "$_sri" ] || _pinned_die "$_name tarball integrity $_got != pinned $_sri"

  rm -rf "$_work/unpack" && mkdir -p "$_work/unpack" "$_dest"
  tar -xzf "$_tgz" -C "$_work/unpack" || _pinned_die "unpack $_tgz"
  cp -r "$_work/unpack/package/." "$_dest/"
  _unpacked=$(node -p 'require(process.argv[1]).version' "$_dest/package.json" 2>/dev/null || true)
  [ "$_unpacked" = "$_version" ] || _pinned_die "unpacked $_name declares version '$_unpacked', not $_version"
  echo "== $_name@$_version: verified $_sri"
}
