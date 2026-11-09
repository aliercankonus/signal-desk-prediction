# REVIEW-ONLY ROOT TERMINAL PREPARATION. Ali runs only after private inputs and separate approval.
# Do not paste into an agent shell; do not run staging in this preparation block.
set -Eeuo pipefail
set +x
umask 077
export PATH=/usr/sbin:/sbin:/usr/bin:/bin HOME=/nonexistent LC_ALL=C
git_safe() {
  timeout -k 2s 15s env -i PATH="$PATH" HOME=/nonexistent LC_ALL=C GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never git "$@"
}
[ "$(id -u)" -eq 0 ] || { printf 'STOP: root terminal required\n' >&2; return 1 2>/dev/null || exit 1; }
MERGE=665698113fcd7d8f7d10a75ee42f67d8a2131166
ADAPTER=eac843de7967d48cce56ee9a198750e98754a2de
RUNNER=e84021a786004456a12de9e25eae50d191da6cf1
BLOB_SHA=e79f337fcbefc4f21f4d6d4abd2e30078227cb0913f242b552630fd110c1dd0d
read -r -s -t 120 -p 'Existing absolute path to root-owned 0600 private staging spec: ' SPEC
printf '\n'
[ -n "$SPEC" ] || { printf 'STOP: no spec supplied\n' >&2; return 1 2>/dev/null || exit 1; }
META="$(timeout -k 2s 15s python3 -I -B - "$SPEC" "$MERGE" <<'PY'
import json, os, pathlib, stat, sys
spec, merge = sys.argv[1:]
def canonical(value):
    if (not isinstance(value, str) or not value.startswith('/') or
        any(ord(c) < 32 for c in value) or '..' in pathlib.Path(value).parts or
        str(pathlib.Path(value)) != value):
        raise SystemExit('STOP: noncanonical private path')
    return pathlib.Path(value)
def trusted(path, private=False):
    for part in (path, *path.parents):
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SystemExit('STOP: untrusted root ancestry')
    if private and path.stat().st_mode & 0o077:
        raise SystemExit('STOP: root directory not private')
p = canonical(spec)
trusted(p.parent, True)
i = p.lstat()
if not stat.S_ISREG(i.st_mode) or i.st_uid != 0 or i.st_mode & 0o077 or not 0 < i.st_size <= 16384:
    raise SystemExit('STOP: spec metadata invalid')
with p.open('rb') as f:
    raw = f.read(16385)
if len(raw) != i.st_size:
    raise SystemExit('STOP: spec changed')
cfg = json.loads(raw)
if any('<' in v or '>' in v for v in cfg.values() if isinstance(v, str)):
    raise SystemExit('STOP: incomplete example spec')
if cfg.get('merge') != 'eac843de7967d48cce56ee9a198750e98754a2de':
    raise SystemExit('STOP: adapter pin mismatch')
store = canonical(cfg['source'])
trusted(store, True)
plan = canonical(cfg['plan'])
trusted(plan.parent, True)
entry = plan.parent / ('operator-bootstrap-' + merge + '.py')
if entry.exists() or entry.is_symlink():
    raise SystemExit('STOP: immutable entry already exists; preserve it')
for value in cfg['excluded_roots'] + [cfg['venv'], cfg['source'], cfg['runner'], cfg['state'], cfg['auth'], cfg['context'], cfg['home'], cfg['inbox'], cfg['bundle']]:
    protected = canonical(value)
    if entry == protected or entry in protected.parents or protected in entry.parents:
        raise SystemExit('STOP: immutable entry overlaps protected path')
print(store)
print(entry)
PY
)"
[[ "$META" == *$'\n'* ]] || { printf 'STOP: private path derivation failed\n' >&2; return 1 2>/dev/null || exit 1; }
STORE=${META%%$'\n'*}
ENTRY=${META#*$'\n'}
[ -n "$STORE" ] && [ -n "$ENTRY" ] && [[ "$ENTRY" != *$'\n'* ]] || { printf 'STOP: invalid derived paths\n' >&2; return 1 2>/dev/null || exit 1; }
[ "$(git_safe --git-dir="$STORE" rev-parse --is-bare-repository)" = true ] || { printf 'STOP: protected source is not bare\n' >&2; return 1 2>/dev/null || exit 1; }
[ "$(git_safe --git-dir="$STORE" cat-file -t "$MERGE")" = commit ]
[ "$(git_safe --git-dir="$STORE" cat-file -t "$ADAPTER")" = commit ]
[ "$(git_safe --git-dir="$STORE" cat-file -t "$RUNNER")" = commit ]
git_safe --git-dir="$STORE" merge-base --is-ancestor "$ADAPTER" "$MERGE"
git_safe --git-dir="$STORE" merge-base --is-ancestor "$RUNNER" "$ADAPTER"
[ "$(git_safe --git-dir="$STORE" cat-file -s "$MERGE:ops/bridge_one_shot/operator_bootstrap.py")" = 26012 ]
[ "$(git_safe --git-dir="$STORE" show "$MERGE:ops/bridge_one_shot/operator_bootstrap.py" | timeout -k 2s 15s sha256sum | cut -d' ' -f1)" = "$BLOB_SHA" ] || { printf 'STOP: immutable blob digest mismatch\n' >&2; return 1 2>/dev/null || exit 1; }
# The only write here is an exclusive 0600 root-private copy from the verified object.
git_safe --git-dir="$STORE" show "$MERGE:ops/bridge_one_shot/operator_bootstrap.py" | timeout -k 2s 15s python3 -I -B -c '
import hashlib, os, pathlib, sys
path, expected = pathlib.Path(sys.argv[1]), sys.argv[2]
blob = sys.stdin.buffer.read(65537)
if len(blob) != 26012 or hashlib.sha256(blob).hexdigest() != expected:
    raise SystemExit("STOP: immutable blob changed")
parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
    with os.fdopen(fd, "wb") as out:
        out.write(blob)
        os.fchown(out.fileno(), 0, 0)
        os.fsync(out.fileno())
    os.fsync(parent)
finally:
    os.close(parent)
' "$ENTRY" "$BLOB_SHA"
[ "$(sha256sum "$ENTRY" | cut -d' ' -f1)" = "$BLOB_SHA" ]
timeout -k 2s 15s python3 -I -B -c 'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_bytes(), filename="operator_bootstrap.py")' "$ENTRY"
printf 'IMMUTABLE ENTRY STAGED ONLY; bootstrap procedure NOT RUN. STOP for operator review.\n'
