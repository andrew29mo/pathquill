# Capacity, safe refusal and retention (P0-1 / P0-2)

The formal daemon now uses ManagedRecorder, which composes the same SQLite
observation/capture implementation with a fixed control record and bounded
retention/reference metadata. No alternate test daemon is used.

## Resource contract

The daemon accepts `--data-bytes` (128..67108864, default 1048576), `--slots`
(1..32, default 32) and `--retention-seconds` (0.1..86400, default 86400).
Short retention is explicitly configurable for controlled tests; it is not a
claim of observing a whole 24-hour production period.

Data accounting includes incident bodies, ring observations and capture copies.
The ring is limited to one quarter of the payload budget, so a recent ring
cannot consume all space needed to copy a new incident after reclamation.
Budget-based ring eviction can shorten the pre-event interval below 60 seconds;
status exposes its actual oldest/latest BOOTTIME values. Existing capture copies
are retained. Coverage never becomes COMPLETE from this operation.

Control storage is structurally bounded: one fixed counter/progress row, at most
one lifetime and one hold per retained incident (maximum 32). Loss/refusal counters
saturate. This is a logical reserved control path, not preallocated disk capacity
or a filesystem quota. DB pages, rollback journal and indexes can consume more
bytes than the payload budget; status reports actual file sizes and free DB pages
separately. Deleting rows enables reuse and does not promise file shrinkage.

## Full data versus storage failure

Logical data refusal increments bounded counters and marks active capture
coverage PARTIAL. Progress can commit through the control row without admitting
another data observation. That explicitly gap-bearing progress permits existing
captures to seal after their real deadline; it does not manufacture completeness.
A full event-slot pool rejects new incidents and never evicts unexpired events.

SQLite/I/O failure disables new writes/probes and administrative mutation. A
running daemon can retain a readable STORAGE_ERROR status; an error on other
write paths may instead make it exit safely. No successful seal is promised when
the filesystem cannot commit even the control record. Removing the external
fault does not silently resume authority: explicit restart is required. Startup
may fail if storage remains unusable. A new epoch invalidates old mutations and
resets progress authority; historical loss/refusal totals remain available.

## Retention and ownership

Retention begins at durable sealing, measured with BOOTTIME. Same-boot process
restart preserves a known sealed anchor and duration. New boot or missing seal
metadata conservatively anchors a full retained duration at startup (86400 seconds if the old duration is
unknown); it can
extend retention but cannot shorten it. Recovery still seals old active captures
PARTIAL/restart. Wall-clock changes are not used for expiry.

Automatic GC uses an independent one-second schedule and transactionally rechecks SEALED state,
current-boot expiry and absence of a hold. Synchronous reconstruction or I/O can
delay an attempt; this is not a real-time scheduling guarantee. It deletes capture, incident and
lifetime rows together. Explicit operator delete may remove an unexpired sealed
incident but also refuses active or held incidents. All administrative mutations
require the current epoch. A UUID hold token protects one incident; holds survive
process restart without timeout or automatic release. Unknown occupancy stays
protected until an explicit fresh-epoch release. These are reservation primitives
for the next milestone, not a completed export lifecycle or external mmap lease.

```sh
python3 -m pathquill.cli --root /absolute/private/store
python3 -m pathquill.cli --root /absolute/private/store --op gc --epoch CURRENT_EPOCH
python3 -m pathquill.cli --root /absolute/private/store --op hold --id INCIDENT_UUID --epoch CURRENT_EPOCH
python3 -m pathquill.cli --root /absolute/private/store --op release --id INCIDENT_UUID --token HOLD_UUID --epoch CURRENT_EPOCH
python3 -m pathquill.cli --root /absolute/private/store --op delete --id INCIDENT_UUID --epoch CURRENT_EPOCH
```

CLI reports `ok:false`, a reason and nonzero exit status for refusal. It does not grant additional
users access; the Unix socket remains private to the service account.

## Reproduction and evidence

In a disposable Linux VM, with Python 3.12+, iproute2, sudo, mount and unshare:

```sh
sudo timeout 100 unshare --mount --net --propagation private python3 tools/capacity.py orchestrate
```

The worker drops to UID 501. [JSON](../evidence/capacity.json) and
[HTML](../evidence/capacity.html) bind runtime/test/runner hashes and environment.
Tests exercise fixed control progress on full data, unexpired refusal, active
protection, held expiry, stale release, conservative cross-boot anchor simulation,
and protected deletion. The formal daemon fixture uses a 4096-byte data budget,
one slot and three-second retention, waits through the real 30-second capture
window, then checks PARTIAL sealing, hold persistence across SIGKILL/restart,
expiry while held, release/GC and capacity reuse by a real refused TCP probe.

A separate formal daemon runs on a dedicated 2 MiB tmpfs filled until ENOSPC.
It refuses mutation, remains faulted after filler removal, then recovers after
explicit restart and rejects the old epoch GC. This is actual filesystem
exhaustion on RAM-backed storage, not SSD corruption or power loss. The mount is
unmounted by the privileged orchestrator, within its private mount namespace.

The ordinary milestone1 real-network regression is rerun for the current source.
Older exploration and reboot reports retain their historical fingerprints.
No new VM reboot, long-term retention duration, clock-step/suspend, physical
media, power-loss, or atomic file-export qualification is claimed. P0-3/P0-4
remain open; this is not a complete public-ready MVP.

## Regression notes

The first capacity run exposed a ring-versus-copy admission dead end after GC;
the ring sub-budget fixes it without deleting any retained capture. The existing
network runner also encountered float subtraction rounding at a BOOTTIME exponent
boundary: end-first could be 29.999999999999545 while end equals first+30. The
assertion now directly compares the stored deadline with first+30, and a regression
still rejects sealing one microsecond before that deadline. This changes no
service deadline or observation window.

## P0 review corrections

The b8d2174 review found GC starvation: repeated failed state rebuilds reset the
GC timer before it could expire. The retry path now updates only its own timer.
A controlled failure-injection case runs the formal serve loop with rebuilds
forced to remain DEGRADED. It seeds an expired incident, an expired held incident
and an unexpired incident through the product API, then admits an active capture
at startup. It requires expired unheld data to disappear while the other three
classes remain. This is an injected reconstruction failure, not real kernel churn.

The capacity runner now accepts only its documented orchestrator entry point;
its internal worker requires complete parameters. The orchestrator requires all
four named cases. The worker writes a private intermediate report; only after
worker success and mount cleanup does the parent publish the final JSON/HTML.
A fresh run first invalidates prior success. A separate process group owns the
worker and its descendants, with TERM/KILL cleanup on every exit, including timeout.
A bounded busy-only unmount retry handles asynchronous FD release without force
unmounting. Tests challenge invalid-mode stale success, descendant heartbeat
continuation after timeout, permanent busy, and nonretryable permission errors.

The full-data case now directly reads the incident deadline and durable control
progress after sealing, rather than inferring the control path from SEALED alone.
It checks deadline >= first+30 and committed control progress >= deadline. Same
boot SIGKILL/restart must preserve the exact stored boot/anchor/duration tuple.
The separate ordinary-network regression still checks the data-progress path.
Neither path establishes power-loss or real-time guarantees.
