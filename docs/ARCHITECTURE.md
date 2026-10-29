> Historical exploration status; current service behavior and remaining gates are in [MILESTONE1.md](MILESTONE1.md).

# Exploration decisions and MVP gate

## Implemented minimum

A single OS-locked SQLite writer uses FULL synchronous rollback transactions.
Incident states are CAPTURING and SEALED; coverage and recovery are separate.
Restart closes prior captures with PARTIAL coverage and restart reason. Epoch
checks reject old completion calls. A window starts 60 seconds before the first
trigger and ends at max(merged trigger+30), capped at first trigger+120; the
minimal core does not yet retain those preceding observations.

Inbox limits count, bytes and individual serialized item size. Its drop counter
is outside the data queue so a full queue cannot hide the known loss count.
Observer retains unknown-count gaps through resynchronization and clears prior
health when generation changes. Each address family has separate health.

Capacity refusal preserves existing incident rows. Explicit delete releases
logical capacity. No automatic retention is implemented. Total payload length
is a logical budget, not a bound on DB, journal, indexes or filesystem allocation.
The public export schema allowlists state, coverage, fixed reason categories,
recovery and per-package endpoint aliases. Unknown/free-text fields are omitted.
JSON bytes are hashed, then escaped into HTML. This hash is not provenance proof.

## Four exploration outcomes

1. Events: real unprivileged link notification works in the tested VM. Sticky
   queue-loss and generation semantics pass core tests. Real ENOBUFS, interrupted
   dumps and notification/dump ordering remain open; no RECORDING confidence gate
   may be based on the current notification-only backend.
2. Time/trigger: synthetic boundary, 180-second inclusive cap, separate families,
   stale generation and watermark refusal tests pass. A short real BOOTTIME
   interval was observed. Wall-clock jumps, suspend and real timeout races are
   untested. Automatic trigger/recovery from actual probe results is not built.
3. Capacity: logical admission refusal and explicit deletion pass; real SQLite
   FULL stops admission. Per-connection readonly injection degrades safely.
   Physical ENOSPC, read-only mount, repair and bounded allocation need testing.
4. Recovery/export: process SIGKILL preserves committed incident data and marks
   it PARTIAL after reopening. Writer exclusion and stale epoch rejection pass.
   Canonical IPv6/hostname aliases and omission of free text pass. VM reboot,
   incomplete physical writes, export publication and complete privacy scanning
   remain unqualified.

## Revised necessary acceptance before MVP

- Persist the bounded pre-event ring and actual observations, with committed
  sequence watermarks and known/unknown gap intervals.
- Implement read-only dumps, capture request sequence/start/end, reject truncated,
  interrupted or failed dumps; bounded retries must remain DEGRADED under churn.
- Integrate numeric-IP TCP and explicit DNS probes with per-family/run authority;
  UNKNOWN cannot restore health. Observe actual failure/recovery in the VM.
- Demonstrate 32 unexpired events reject the 33rd without deletion, and bounded
  payload/count/queue/temporary/export allocation under sustained overload.
- Add explicit durable mutation failure handling to every write path, not only
  admission. Check physical ENOSPC/read-only, repair, and crash commit boundaries.
- Define bounded export snapshots/references, cancellation, cleanup and atomic
  publication before introducing concurrent file export and retention GC.
- Exercise ordinary VM reboot with pending state preserved; do not substitute
  graceful stop for abrupt crash. Power loss remains a separate qualification.
- Scan all exported fields, names, errors and HTML for synthetic sensitive
  identifiers and injected markup. Local raw data remains private by design.

Decision: continue only through these bounded gaps; existing evidence supports
core primitives, not whole-service completeness. No autostart, zero-gap boot,
power-loss recovery, WAN diagnosis or long-term stability claim is authorized.

## Continuation supersedes the initial exploration status

See [CONTINUED.md](CONTINUED.md) for current evidence and remaining gates.
The original four outcomes above are historical. The current Recorder adds a
persistent prebuffer and capture copies, real TCP/DNS trigger calls, real dump
interval evidence, filesystem ENOSPC/refusal-and-repair and normal VM reboot.
It does not yet implement the full daemon. Admission and prebuffer copy are a
single transaction; failed capacity admission rolls back the new incident.
Dedicated export file budgets and retention are deferred until a formal file
export interface exists. Raw local observations stay private; only a fixed
allowlist can leave the recorder through the current export API.


## Reviewed contracts

The continuation review in CONTINUED.md supersedes the initial capacity and
prebuffer details: total logical payload accounting includes incident metadata,
ring and capture copies; expired capture merges fail; delete reclaims capture
rows; same-boot recent prebuffer survives process restart with UNKNOWN coverage.
Cross-boot data remains historical and is not reused as current prebuffer.
Read-only dumps require unique request sequences and explicit loss rejection.
Store directory ownership/private mode and numeric probe endpoints are enforced.
These are exploration-core contracts, not whole-service qualification.

## Milestone 1 supersedes the exploration-only service status

See [MILESTONE1.md](MILESTONE1.md) for the formal daemon, quiet-round state
reconstruction, generation-bound workers and writer-commit-driven sealing.
Capacity/export/deployment gates remain open. Historical exploration source
fingerprints are retained and must not be treated as qualification of new code.


Milestone review tightens observed recovery to post-incident probe starts for
all targets, preserves generation rejection before DB/health mutation, and uses
one fresh post-commit decision time at deadline boundaries. See MILESTONE1.md for
the exact VM overlap and persisted barrier checks and remaining test limits.

## Capacity/retention stage

[CAPACITY.md](CAPACITY.md) supersedes the original fail-on-logical-capacity and
no-retention behavior. ManagedRecorder separates bounded control progress from
data payload admission, conservatively anchors retention, and performs atomic
eligibility-checked GC. Export-file lifecycle remains deferred.


The P0 review separates GC scheduling from failed reconstruction retries and
requires parent-owned success publication after worker/group/mount cleanup.
See CAPACITY.md for the formal-loop failure injection and retained-data checks.
