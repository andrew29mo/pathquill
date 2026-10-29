# Durable export requests and deidentified fixed snapshots (P0-3a / P0-3b)

The formal daemon now uses ExportRecorder, extending the same capacity/retention
core. This stage produces a private SQLite snapshot and an escaped HTML preview
returned over the existing Unix socket. It does not publish export files.

## Requests and authority

`export` requires current epoch, a sealed source UUID, request ID (1–64 ASCII
letters/digits/underscore/hyphen) and fixed total seconds (0.1–60, default 30).
The durable request contract includes the source, normalized duration and
`pathquill-snapshot-v1`. Repeating an ID returns its original state/deadline;
changing parameters is rejected. Reusing an interrupted or cancelled ID never
restarts it. A new attempt requires a new ID.

At most one QUEUED/SNAPSHOTTING job is allowed, with 32 retained request records
and no automatic history rollover. Admission reserves a maximum 256 KiB snapshot
against a separate 1 MiB total snapshot budget. Cancellation frees snapshot bytes
but not the request-history slot. Input is capped at 4096 observations / 1 MiB
raw bodies; output above 256 KiB fails safely rather than dropping observations
silently. These are logical budgets, not filesystem quotas.

Request admission and an `export:`-namespaced source hold commit in one SQLite
transaction. Normal hold/release APIs cannot take or release this reference.
GC/delete use the existing hold checks. A completed snapshot, its digest, job
state and release of the exact owned reference commit in one transaction. The
source can then be reclaimed independently of the stored snapshot.

## Lifecycle

```text
QUEUED → SNAPSHOTTING → SNAPSHOT_READY
   ↘ CANCELLED / EXPIRED / INTERRUPTED / FAILED
   ↘ BLOCKED (ownership cannot be confirmed)
```

The writer advances a stage on a one-second scheduler. Snapshot construction is
synchronous and bounded by input/output limits; this is not a hard execution or
I/O latency bound. Deadlines are checked before work and before ready intent;
synchronous SQLite commit can still delay a response. Cancellation runs on the
same writer: it occurs before construction or after that atomic step, never
halfway through a committed snapshot. READY cancellation removes its stored
snapshot/digest; nothing has been publicly published.

On process restart, unfinished jobs become INTERRUPTED and release only an exact
matching owned hold, in the same transaction. They do not resume or extend their
deadlines. Ready bytes are retained unchanged. Mismatched ownership becomes
BLOCKED and never releases the different owner's hold. BLOCKED prevents new
exports; an operator repair interface is deferred. This fail-closed state is a
limitation, not automatic recovery. All mutation calls reject prior epochs.

## Snapshot and privacy contract

SEALED sources are immutable through product APIs; their UUID identifies the
fixed source version. Snapshots preserve incident coverage/recovery separately,
observation order and relative times. Capture rows now store their observation
time; legacy rows with no time export null, without invented chronology. Order
is writer order, not a claim of cross-source causal order.

Only typed fields pass the versioned allowlist. Addresses, MACs, hostnames and
interface identifiers use canonical per-snapshot aliases. Supported link/address/
route attributes are decoded into aliases; raw hex attributes, arbitrary text,
source IDs, request IDs, boot IDs, filesystem paths and raw-identifier hashes do
not enter snapshots. Unknown fields are omitted; malformed supported values
fail snapshot creation. A snapshot need not retain every raw Netlink detail.

Alias maps are transient and not stored in the snapshot. No stable cross-package
identity mapping is provided; topology, ordering and timing may still permit
inference, so this is not a promise of complete anonymity. Local source DB and
private administrative status intentionally retain original values. Deleting
rows is not secure erasure of SQLite pages or journals.

`export-read` returns only the sanitized snapshot, its SHA-256 and escaped HTML
preview (no mixed raw daemon status). The hash covers sanitized JSON bytes and
checks consistency, not publisher identity. Other status/control responses remain
private administrative data and must not be treated as public export artifacts.

## CLI

```sh
python3 -m pathquill.cli --root /absolute/private/store --op export --id SOURCE_UUID --request incident_001 --seconds 30 --epoch CURRENT_EPOCH
python3 -m pathquill.cli --root /absolute/private/store --op export-status --request incident_001
python3 -m pathquill.cli --root /absolute/private/store --op export-cancel --request incident_001 --epoch CURRENT_EPOCH
python3 -m pathquill.cli --root /absolute/private/store --op export-read --request incident_001
```

## Reproduce and assess evidence

In the isolated Linux VM (UID 501 fixture identity), run:

```sh
sudo timeout 40 unshare --net python3 tools/export_snapshot.py orchestrate
```

The parent requires all three named cases, owns a separate worker process group,
invalidates old success before starting and publishes final verification reports
only after worker/group cleanup. [JSON](../evidence/export-snapshot.json) and
[HTML](../evidence/export-snapshot.html) bind runtime/tests/runner fingerprints.
These verification reports are distinct from product export publication.

The fixture seeds synthetic sensitive observations using the product API, then
starts the actual daemon and uses the real Unix client. It verifies dedup and
conflict rejection, protected delete/GC, cancellation followed by a new manual
holder, fixed snapshot after expired source GC, and SIGKILL/restart preserving
ready bytes while interrupting a pending job without releasing other owners.
Sensitive-value scanning covers the actual returned snapshot and HTML preview.

Unit regressions additionally cover SNAPSHOTTING/READY cancellation, unknown
ownership, finite history, canonical IPv6/MAC/name aliases, unchanged deadlines,
SQLite admission-abort rollback and snapshot-commit abort preserving the hold.
Those aborts use SQLite triggers, not physical storage fault injection. Existing
capacity/ENOSPC and live-network regressions are rerun for the current runtime;
they do not establish every export-specific I/O crash boundary.

No VM reboot, sudden power loss, atomic export-file publication, file cleanup,
external-reader lease, full Linux-attribute coverage or long-term qualification
is added. P0-4 and formal deployment remain open. GitHub stays Private and the project now uses [MIT](../LICENSE).

## P0-3 review corrections

The ca0681f review found two daemon defects. An extremely large integer duration
could overflow math.isfinite before range rejection; range validation now happens
first, with no DB mutation on refusal. A successful export-read previously
continued the outer loop before scheduling/progress work. It now sends the same
sanitized-only response and then runs normal lifecycle work in that iteration.

Regression covers the huge-duration RPC against the actual daemon and verifies
its epoch remains unchanged. Six concurrent clients continuously read the READY
snapshot while a separate read-only SQLite check requires durable control progress
to advance during the load. This proves writer progress, not every scheduler
subsystem under every load. Current reports retain the observed read count and
relative progress time; no throughput or latency guarantee is inferred.

Redaction validation now has positive checks, not only absence scans: synthetic
link, address and route state must survive; interface/IP/MAC aliases must retain
their required relationships and a distinct destination must stay distinct.
New state observations include an allowlisted group discriminator. Previously
stored immutable snapshots may lack this optional discriminator and are not
rewritten. Removing all state data no longer passes the privacy fixture.

Storage errors retain the existing safe-exit contract: a SQLite error may stop
the daemon rather than always exposing a live STORAGE_ERROR interface. The
transaction-abort tests verify rollback and preservation of the hold, followed
by explicit repair/restart interruption. They are not physical export-transaction
ENOSPC or power-loss qualification. File publication remains unimplemented.

## Subsequent publication slice

P0-4a/b now adds explicit private JSON/HTML package publication; see
[PUBLICATION.md](PUBLICATION.md). Earlier no-publication statements describe
the snapshot-only milestone and its evidence. P0-4c now adds interrupted-publication reconciliation and known-staging cleanup;
see [PUBLICATION_RECOVERY.md](PUBLICATION_RECOVERY.md). Explicit published-artifact retirement and full-history handoff are now
documented in [RETENTION.md](RETENTION.md); external-reader leases remain deferred.
