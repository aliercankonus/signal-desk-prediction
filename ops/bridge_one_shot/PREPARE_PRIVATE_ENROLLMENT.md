# Operator step: cold private inputs

Use this step only after the accepted #59 workspace receipt. The manager supplies
one immutable loader with the existing private workspace and image ID already
filled in. No JSON construction, old profile copying or manual file editing is
needed. `--provision` explicitly creates **new credentials on the operator host**;
this repository merge does not perform that action. Default invocation is a
preview with no secret prompts, key generation or writes.

The root entry checks the protected workspace/public guide digests, pinned
bootstrap source, immutable image metadata and bounded current container mounts.
It reads image environment **names only**, never values. Image contents/global
isolation and actual worker authentication are still UNPROVEN. The accepted
source preparation and historical runner are preserved; no repeated fetch,
chown, worker/container launch, service, firewall, scheduler, provider login,
signature, grant, GitHub write or task dispatch occurs.

## Two unavoidable browser actions

The program prints one GitHub fine-grained token creation URL per role. While
it waits, open the URL using the owner's browser account. Select **Only select
repositories → aliercankonus/signal-desk-prediction**. The URL cannot preselect
the repository; verify this choice yourself. Use two distinct newly generated
tokens, a 30-day expiry, and only the permissions below. Do not use classic PATs,
existing broad tokens, workflow, administration, secrets or organization scopes.

| Repository permission | Root readback/publication token | Worker token |
|---|---|---|
| Contents | Read | Read and write |
| Issues | Read and write | Read and write |
| Pull requests | Read | Read and write |
| Actions | Read | Read |
| Commit statuses | Read | Read |
| Metadata | GitHub required read | GitHub required read |

Keep both creation tabs open until the final receipt. Paste each token **only**
into its hidden root-terminal prompt. Never paste it into ChatGPT, an issue,
shell command, environment variable or a log. Terminal echo is disabled and
restored on success/interruption. Each prompt has a ten-minute bound; the whole
input collection has a thirty-minute bound. The loader's stdin can be a heredoc;
secret entry always opens `/dev/tty`, without an echoing stdin fallback.

The entry performs authenticated GETs for identity, repository, historical
check-run listing and Actions listing. Every request uses a fixed HTTPS host,
allowlisted route, no redirects/retry and bounded time/response size. Public
repository GET success does **not** establish write permissions, single-repo
restriction, token expiry, Checks API entitlement or actual worker access.
Requested browser scope is operator-declared; the receipt distinguishes it from
verified host GETs. A rejected endpoint stops; never widen to a classic token.
The historical probe SHA is not new task CI acceptance. Same-account identity
is not manager task authority; exclusive manager/App invocation remains UNPROVEN.

After both tokens pass, the system OpenSSL CLI generates an unused Ed25519 pair.
The entry exclusively creates an intent, key pair, two token files and a receipt
under the existing root-private workspace. Files are root-owned 0600 with fsync;
no overwrite or rollback. No credential is installed into a worker. No private
key is used to sign anything. The helper suppresses core dumps for its process;
independent host image/root isolation proof remains necessary.

## Immutable entry loader

The manager fills these four nonsecret values privately and supplies this whole
block. It downloads only the fixed public helper, checks SHA256 **before** exec,
and does not save the downloaded source. Do not run with placeholders. This is
an operator credential-creation step, not runtime enrollment/activation authority.

```bash
env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  SD_PRIVATE_ENTRY_COMMIT='MANAGER_REVIEWED_COMMIT' \
  SD_PRIVATE_ENTRY_SHA256='MANAGER_REVIEWED_SHA256' \
  SD_PRIVATE_WORKSPACE='MANAGER_SUPPLIED_PRIVATE_WORKSPACE' \
  SD_PRIVATE_IMAGE='MANAGER_SUPPLIED_IMMUTABLE_IMAGE' \
  /usr/bin/python3 -I -B - <<'PY'
import hashlib, os, re, signal, sys, urllib.request
commit = os.environ['SD_PRIVATE_ENTRY_COMMIT']
digest = os.environ['SD_PRIVATE_ENTRY_SHA256']
workspace = os.environ['SD_PRIVATE_WORKSPACE']
image = os.environ['SD_PRIVATE_IMAGE']
if (os.geteuid() != 0 or not re.fullmatch('[0-9a-f]{40}', commit) or
        not re.fullmatch('[0-9a-f]{64}', digest) or not workspace.startswith('/') or
        not re.fullmatch('sha256:[0-9a-f]{64}', image)):
    raise SystemExit('STOP: INVALID_REVIEWED_ENTRY_INPUTS')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('redirect denied')
def timeout(*args):
    raise TimeoutError()
previous = signal.signal(signal.SIGALRM, timeout)
signal.alarm(20)
try:
    url = ('https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/' +
           commit + '/ops/bridge_one_shot/prepare_private_enrollment.py')
    with urllib.request.build_opener(NoRedirect).open(url, timeout=15) as response:
        source = response.read(32769)
    if len(source) > 32768 or hashlib.sha256(source).hexdigest() != digest:
        raise ValueError('digest mismatch')
except Exception:
    raise SystemExit('STOP: PUBLIC_ENTRY_FETCH_OR_DIGEST; no private inputs created')
finally:
    signal.alarm(0)
    signal.signal(signal.SIGALRM, previous)
sys.argv = ['reviewed-cold-inputs', '--workspace', workspace, '--image', image, '--provision']
exec(compile(source, '<reviewed-cold-inputs>', 'exec'), {'__name__':'__main__'})
PY
```

Expected sanitized receipt:

```text
MANAGER_KEYPAIR: COLD_STORED_ROOT_ONLY
ROOT_GITHUB_READS: VERIFIED_HOST_ONLY
WORKER_TOKEN_READS: VERIFIED_HOST_ONLY
PRIVATE_INPUTS: COLD_READY; worker/provider enrollment not installed
OVERALL: NO-GO — no signer, service or task activated
```

On STOP, timeout or interruption, preserve any intent/files, browser-created
new tokens and private state for read-only reconciliation. No automatic retry,
cleanup, replacement or revocation. Browser-created tokens may exist even when
local publication never began. Return only the fixed summary/STOP lines, never
raw exceptions or secret-bearing state. A GitHub HTTP 403/429 is endpoint evidence,
not evidence of model/provider quota or its reset time. After a successful
receipt, manager prepares the next bounded enrollment step; cold files alone
never authorize first dispatch, provider login or hourly activation.

The durable operator chain is #41/#45. #44 remains the subsequent single portable
application container and separately secured persistent backup/restore deliverable;
this existing image/private venv is not claimed portable.

Primary permission references:
- https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
- https://docs.github.com/en/rest/checks/runs?apiVersion=2022-11-28
