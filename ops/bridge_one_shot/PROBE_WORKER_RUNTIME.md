# Worker capability boundary after successful inert staging

This is a new, explicit **operator-only runtime probe**, not another staging attempt.
The manager automation must never invoke it on the host. Its default mode validates
existing protected preparation records without invoking Docker. `--probe` creates,
starts, and removes exactly one new temporary container. It does not enroll a worker,
install a watcher, start a project service, provision credentials, authenticate a
provider, sign a task, contact GitHub, or dispatch/retry any task.

The operator uses the existing private workspace. Do not publish its paths, image
metadata, tokens, raw logs or private records. The manager supplies the known path
privately; no manual JSON/spec or token re-creation is required.

The helper requires the successful #67 staging receipt, unchanged original spec and
matching root-owned plan/setup/cold metadata. It never opens root/worker tokens,
private keys or auth stores. It preserves every original staging file, scope window,
cursor, credential and historical run. It mounts only the worker-owned runner and
venv, both read-only, in a nonroot UID:GID 10000:10000 container using the existing
immutable image without pulling. Networking is `none`; root filesystem read-only;
capabilities dropped; privilege escalation disabled; memory, CPU, PID, command time
and output bounded. Fresh tmpfs masks the old `/opt/data` tree except the specific
read-only venv, and provides a fresh home. No existing container is executed or changed.

The actual worker namespace checks Git HEAD/cleanliness without `safe.directory`
exceptions, test interpreter version and installed pytest metadata, and whether
`git`, `gh`, and `hermes` are on PATH. Hermes/provider code is not executed. No model
requests or new full test run occur. Tool presence does not prove login support,
provider entitlement, dependency completeness, image credential absence or global
isolation. These and manager/App exclusive invocation remain separate gates.

An exclusive root-only intent is written before create. A returned exact container
ID is durably recorded and its image, label, mounts and confinement are verified
before start. A client timeout does not mean the container stopped: cleanup verifies
that same ID, kills it if running, verifies stopped, removes only it, then checks
absence. No forced removal, volume deletion, prune, Compose down or guessed-ID
cleanup. Lost create response or identity mismatch preserves the intent/container
for review; it never adopts a name/filter match as authority. Any prior probe intent
blocks a second invocation, even after successful cleanup.

Only after merge and immutable source/hash verification, the operator entry is:

```bash
python3 -I -B /reviewed/private/probe_worker_runtime.py --workspace /existing/private/workspace --probe
```

The manager supplies a filled, digest-verified loader privately; placeholders above
are a procedure illustration, not a copy/paste host command.

Expected `WORKER_RUNTIME: CAPABILITY_PASS` or `BLOCKED`, individual fixed PASS/FAIL
lines, `PROBE_CONTAINER: EXACT_ID_REMOVAL_VERIFIED`, and overall NO-GO. Missing tools
or declared-version mismatch are evidence to fix, never permission to install or
retry automatically. On STOP, timeout, interruption or absent cleanup confirmation:
preserve all files/intents, do not repeat, delete, clean, or switch attempts. Report
only the fixed sanitized receipt; never paste tokens/private state.

The frozen `operator_host.py --execute` entry remains blocked: it checks a now
worker-owned runner using root Git. A separately reviewed adapter must move that
check into the actual worker namespace before auth/task effects, preserving Git's
ownership protection and versioning source/manifests. This probe does not patch the
staged adapter or authorize that execution. #45 remains dormant; #44's portable
single application container/secured restore deliverable remains subsequent work.
