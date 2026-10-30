# Final pre-publication review

Date: 2026-10-29. Reviewed code/test/evidence baseline: ed781910be7e7f6227450f19ab946c23ecb95805.
Follow-up changes in this review clarified documentation only; production code,
tests, deployment assets and qualification reports remained at that same content
at review time; subsequent demo changes are described in USE_CASE.md.
GitHub was Private during this review. The subsequently authorized public
release is recorded in [PUBLIC_RELEASE.md](PUBLIC_RELEASE.md). MIT was selected after this review; see the licensing
addendum in [DEPENDENCIES.md](DEPENDENCIES.md).

## Code, tests and claims

Two independent read-only reviews found no confirmed release-blocking runtime
correctness/security defect within the existing bounded Linux contract. This is
not a new hardware, long-term, reboot or production qualification. The full Linux
source suite was rerun in the existing isolated VM: 111 tests passed.

Seven current regression reports (deployment, retention, publication recovery,
publication, export snapshot, capacity and milestone 1) each record the same
111 distinct source tests. At this review, runtime/test fingerprints matched the recorded baseline; the original pyproject
fingerprint predates the licensing-only metadata addition documented in
DEPENDENCIES.md.
The closeout report's installed-module fingerprints match production source.
The later demonstration adds tools/tests with separate evidence in USE_CASE.md.
All top-level JSON/HTML report pairs represent identical objects. Resource
summary recomputation matches the report and fixed acceptance limits:

- About 330 seconds, 9 real fault/recovery/export/retire cycles, 161 samples.
- One service PID/invocation/epoch with no restart during that observation.
- Warmed RSS 20,860–21,888 KiB; warmed-window median growth 872 KiB.
- FD 7–8, threads 2; maximum sampled allocated store bytes 786,432 (768 KiB).
- Both failures, the first passing observation and final same-source result are
  retained. No acceptance threshold was relaxed to obtain the passing result.

Historical exploration/continued/reboot reports intentionally retain their
recorded older source fingerprints. Their normal-reboot result is not evidence
for the latest installed daemon. README and stage headings now make this
separation explicit. See [CLOSEOUT.md](CLOSEOUT.md) for the full measured scope.

## Content and history inspection

The reviewed baseline has 17 reachable commits and 295 unique file blobs. All
were text; no committed database, wheel, private-key file, environment file,
personal Codex instruction/log, VM image or raw store was found. Pattern checks
for recognizable credential formats, private home paths and contact addresses
found no such content in those file blobs. Synthetic network addresses and
fixture names are intentional test data, not captured customer data.

Commit metadata is a separate surface: the root commit still uses a local-machine
identity for both author and committer. Other commits use GitHub noreply. The
original local identity is deliberately not reproduced in this document. It is
not a password/token, but it is an owner privacy decision before publication.
No remote history rewrite or force push has been performed. A content-preserving
local rewrite candidate can be reviewed separately; changing remote history
requires explicit authorization. A history rewrite alone must not be presented
as guaranteed deletion of any hosted/cached old object.

These inspections are pattern/content reviews, not proof against every possible
encoded secret or a guarantee of complete anonymity. Raw stores and archive
receipts must stay private; sanitized exports are a narrower allowlisted format.

## Repository and release state

Read-only GitHub checks confirmed the intended owner/repository, Private main,
no selected license at review time, only the owner as collaborator, and no open pull request.
There are zero Actions workflows. Actions itself is enabled with all actions
allowed; its default workflow token is read-only and PR approval is disabled.
No remote CI pass is claimed: verification is the recorded local Linux work.
This review did not change access grants or repository security settings.

The main-protection API returned an unavailable-feature response in the current
private-repository account context; no enablement was attempted. Secret-scanning/push-protection status was
not returned, so neither is claimed enabled. Once publication is explicitly
authorized, recheck and apply the intended public-repository protections; these
checks are not a substitute for that step.

## Decisions recorded at review time and tested boundaries

- Decide whether to retain the historical local-machine commit identity or
  explicitly authorize the reviewed metadata-only rewrite.
- License decision completed: [MIT](../LICENSE), with the inventory in
  [DEPENDENCIES.md](DEPENDENCIES.md).
- Public visibility was subsequently authorized and applied; see
  [PUBLIC_RELEASE.md](PUBLIC_RELEASE.md). The API observations above describe the
  earlier private-repository review, not current public security settings.

The functional scope is frozen: Linux-only service; bounded storage/export
budgets; 32 permanent request-history slots per store; explicit raw-data deletion,
package retirement and manual seal/archive/new-store handoff. No automatic
rollover, external-reader lease, complete network-state history under continuous
churn, WAN diagnosis, long-term stability, installed-service VM reboot/autostart,
power-loss recovery or zero-gap boot guarantee is added.
