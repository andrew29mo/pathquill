# Public release record

On 2026-10-29 the owner authorized publication. Pathquill is Public under the
[MIT License](../LICENSE). The original Git history is retained; no metadata
rewrite or force push was performed. Historical pre-license/private labels in
measurement reports describe the original validation stage and are preserved.

## Protections

- Secret scanning and secret-scanning push protection enabled.
- Private vulnerability reporting enabled; see [SECURITY.md](../SECURITY.md).
- main requires linear history and conversation resolution, blocks force pushes
  and deletion, and enforces protection for administrators too.
- Required PR reviews and status checks are not imposed, preserving a single
  maintainer's direct-push workflow. Only the owner has collaborator access.
- There are no Actions workflows. Actions is disabled; the default workflow
  token permissions remain read-only with PR approval disabled. No remote CI
  pass is claimed.

Dependabot security updates, non-provider secret patterns and secret validity
checks are not claimed enabled by this release record. Protections are repository
settings, not proof that the application is production-ready.

## Verification scope

The public README, MIT text and JSON/HTML evidence must be reachable without an
Authorization header. At publication, code/test fingerprints matched the recorded Linux validation,
apart from licensing metadata. Later demonstration tools/tests have their own
evidence in USE_CASE.md; application runtime bytes remain unchanged. The original pyproject SHA and wheel digests remain historical,
as explained in [DEPENDENCIES.md](DEPENDENCIES.md).

The bounded closeout covered about 330 seconds, 9 actual TCP fault/recovery/export/
retire cycles and 161 samples with no service restart during that observation.
That closeout recorded 111 distinct source tests, not 777 distinct tests across seven repeated
regression runs. See [CLOSEOUT.md](CLOSEOUT.md) for precise evidence and thresholds.

Request history remains limited to 32 entries per store, followed by explicit
seal/archive/new-store handoff. Long-term rollover, installed-service VM reboot/
autostart, abrupt power loss and zero-gap boot remain unverified. Publication
adds no new runtime or recovery qualification.
