# Recovered runner integration gate (dormant source)

`recovered_runner_binding.bind` proposes a frozen-host Plan using only the exact
recovery-02 runner. It reads the root-ready/local report intent/receipt and
independently authenticated GitHub receipt 6825239944, checks old-plan transition,
preserved prefix/source refs, exact unedited instruction/policy/scope, empty
journals/queue and absent inbox/signer claim. It does not modify a file, import
worker code, run root Git against the worker clone, sign, dispatch or start a
lifecycle. The old home/context/auth/pins/history are retained. Ordinary detached
Git HEAD mode 0644 is validated through a bounded no-follow reader; ownership
protections are not disabled.

This component is NOT an operator entry or a complete runtime integration.
A later reviewed root caller must hash-verify the frozen host, a2, recovery-v2
and this gate before importing them, then bind the returned plan to unchanged
frozen lifecycle/Bridge supervision. Worker-side Git cleanliness/context checks
remain necessary under the worker UID; root HEAD-byte observation cannot prove
checkout cleanliness or runtime capability. The returned object is a proposal,
not task authority. No RUN or effectful continuation follows from CI/merge.
The existing limited conversation approval and instruction 6824067293 must be
assessed against that complete package. No old entry/intent may be reset/resumed.

Offline fixtures exercise the actual binding gate and real filesystem HEAD/
receipt mutations, with explicit ownership/module seams; actual cross-UID/VPS
and live GitHub behavior are not proven. The frozen binding/lifecycle modules
are reused, not reimplemented. #45 timer remains dormant, #44 subsequent.
