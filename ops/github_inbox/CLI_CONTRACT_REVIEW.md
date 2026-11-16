# Native CLI declaration audit, source only

The consumed a2 report #41 comment 6909669368 confirms child exit 1 after
worktree creation, no recorded head or PR, and operator-reported cleanup.
Historical stdout was discarded. This does not identify a CLI/provider cause.

The frozen HermesAgent.check uses substring membership against help text.
Consequently `--input` can satisfy `--in`, and prose can satisfy any required
flag. The a2 wrapper also appends `--provider openai-codex`, while the frozen
FLAGS check omits `--provider`. These are directly inspected source gaps,
not evidence that the installed historical CLI rejected these arguments.

cli_contract_v1.audit_help is a dormant, bounded text-only declaration audit.
It checks exact options in conventional indented argparse/click declaration
signatures, including provider, and returns only fixed booleans/options/hash.
Unknown or decorated formats fail closed. It does not import or execute Hermes,
read files/auth, contact a provider, or grant task authority. No runtime entry
or frozen runner is modified. Passing this audit does not prove option value
semantics, selected native/gateway mode, installed source identity or inference.

Before any later task, bind an independently reviewed installed CLI/source
identity and actual parser contract to the complete versioned command/capture
package. Do not substitute current upstream main for installed bytes. Help alone
cannot prove runtime behavior. Offline regression tests use only synthetic text.
The old instruction/approval is consumed. Preserve every claim/auth/history/pin;
no old task or diagnostic rerun, no new RUN/grant/model/dispatch is authorized.
Any later real attempt requires a concrete complete reviewed fresh-identity
package and NEW explicit bounded conversation approval. #45 remains dormant.
