# Worked-example review (2026-11-01)

The review covers the installed-service example, public package, manual commands
and their verification. No pathquill/ runtime, deployment unit or application
feature was changed. Two read-only reviews found demonstration issues; the
following targeted corrections were applied:

- Private output directories/traces follow checkout ownership rather than a
  fixed UID501. A Linux root test exercises a UID/GID1000 checkout: UID1000 can
  read its 0600 trace; a distinct UID501 cannot. The demo's public report also
  follows checkout ownership. Operators should use a checkout they own.
- Actual documented Bash readiness code is tested under set -e for both an
  initial failure followed by readiness and permanent failure. An explicit
  destination guard rejects existing files/directories/dangling symlinks before
  copying; each case is executed in a regression test. Exact history-full/quota/
  hold checks precede raw deletion; process exit precedes offline archiving.
- Known-value checks include decoded JSON and non-interface route destinations,
  gateways and preferred sources. Meaningful address/link/route aliases and the
  exact escaped HTML are required. Valid hashes cannot hide a Unicode-escaped
  known value, empty state context or an appended HTML script.
- Cleanup-only completed failures are retained as failed attempts. In-progress
  markers are not treated as complete qualification results.

## Final execution

The actual wheel, systemd unit and subprocess CLI were rerun in an isolated
Colima Linux VM with fresh application paths. This review used a newly created
Colima Docker-runtime VM; Pathquill itself ran directly under systemd, not in a
container. No clean-OS installation or VM recovery qualification is inferred.

All 123 tests passed on Linux with no skipped tests, including the real UID
permission test. The single complete example took about 73 seconds and all three
required cases passed: real TCP failure/recovery/export; verified copy, retirement
and raw reclamation; 32-slot refusal and explicit archive/new-store handoff with
fresh real work. Orchestrator cleanup passed. Current code, guide and installed
module fingerprints are recorded in [JSON](../evidence/use-case.json) and the
identical [HTML](../evidence/use-case.html). All 14 runtime module bytes remain
unchanged from the published implementation.

The current package was checked against 28 known fixture/administrative values.
This remains a finite disclosure test, not universal anonymity certification.

## Immutable public example

The original three public package files remain unchanged. Their associated
[original JSON](../evidence/use-case-original.json) /
[HTML](../evidence/use-case-original.html) are exact copies of the previously
published report and retain its source fingerprints, 115-test result, 362
observations and 16-value check. The current stronger checker also accepts this
original sample. The current report's new local output must not be substituted
as provenance for that original sample.

Earlier 111-test resource/benchmark records also retain their historical scope.
No new long-term, WAN, installed-service VM reboot/autostart, power-loss or
zero-gap-boot evidence was produced. No external-user usability test or outreach
has occurred. The functional scope is frozen pending actual user feedback.
