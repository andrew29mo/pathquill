# Interrupted publication reconciliation and cleanup (P0-4c)

The actual daemon now reconciles all retained publication records at startup
(maximum 32 request-history records), before serving clients. The same logic is
available through an epoch-bound publication-reconcile operation. This extends
P0-4a/b; it does not introduce automatic re-publication or published-file deletion.

## Decision matrix

| Evidence | Result |
| --- | --- |
| Final alone, exact expected JSON/HTML/manifest, matching recorded directory identity when available | fsync directory/parent, record PUBLISHED without rewriting |
| Known staging only, supported files with exact or prefix expected bytes, matching persisted directory identity | persist cleanup inventory, then CLEANUP_PENDING |
| No staging/final for unfinished intent | persist empty cleanup intent, complete as interrupted/expired/cancelled |
| Both paths, unexpected types/names/content, replaced identity, unreadable files | BLOCKED, preserve files and full reservation |
| Previously delivered package missing or damaged | BLOCKED, including across repeated restarts; never reinterpret as disposable unpublished work |

All expected content is regenerated from the immutable sanitized SQLite snapshot
and compared with its stored digest and reservation size. Final adoption also
checks exact bytes of all three files, not only a self-described manifest.
Paths are derived from validated opaque package IDs. Symlinks, nested/extra files,
non-private ownership/mode, multiple links and changed content are not cleaned.
Unknown unrelated entries in packages are never swept by name or age.

New publications record staging device/inode after mkdir and before file writes.
A crash between mkdir and recording identity can leave an unproven directory;
that intentionally stays BLOCKED. Older records without identity may adopt a
fully verified final, but may not delete existing staging. This migration favors
preservation over automatic reclamation. Existing PUBLISHED rows gain a durable
delivered marker; an artifact becoming missing cannot lose that fact on restart.

## Cleanup and cancellation boundaries

```text
PREPARING / BLOCKED --reconcile--> PUBLISHED
                       |-------> CLEANUP_PENDING --> CLEANED
                       |-------> BLOCKED
```

Before deleting any file, SQLite commits CLEANUP_PENDING, intended terminal
outcome and an inventory of present filenames, device/inode, byte lengths and
content hashes. Only matching remaining files are eligible. Missing files after
this durable intent are permitted, so a crash after unlink can resume. Added or
replaced files instead block cleanup. The single writer holds the existing
exclusive store lock throughout these operations; there are no detached cleanup
executors.

The scheduler deletes at most one file per one-second export turn and syncs the
staging directory. Once empty, it removes the directory and syncs packages. Only
then does one SQLite transaction mark CLEANED, set publication bytes to zero and
release the saved snapshot bytes, recording INTERRUPTED/EXPIRED/CANCELLED on the
export. No source hold is released here: the original snapshot step already
released its exact source hold. These I/O operations are synchronous and bounded
in input size, not guaranteed in latency.

Until that final transaction, the full original publication reservation remains
visible in publication-status.bytes and the snapshot remains protected. Any
unresolved publication (including CLEANUP_PENDING/BLOCKED) blocks new publication;
free filesystem bytes from a partial unlink cannot bypass that gate. Snapshot
history/request slots are retained after cleanup, not rolled over. A failed
SQLite commit cannot report cleanup success or release credit early. On storage
error the existing safe-exit/degraded contract still applies.

Cancel on an interrupted job reconciles first. A verified final returns
already_published. Known unpublished work persists outcome CANCELLED and returns
CLEANUP_PENDING; cancellation is accepted, but cleanup is not yet complete.
Outcome is visible in publication-status. A terminal CLEANED record stays terminal
and cannot publish again under the same request. Unknown data returns
publication_requires_reconciliation without deleting anything. Mutation calls
reject prior epochs. Original deadlines are not extended; expired or cross-boot
unpublished work can only be retired, never resumed. Complete final adoption does
not create new exposure, even if its original deadline has passed.

A retry of an already published request revalidates its files before reporting
success. Read-only status is the last recorded result, not a continuous filesystem
integrity monitor. The private same-UID trust boundary still applies; this is not
protection against a malicious administrator racing filesystem operations.

## Operations

```sh
python3 -m pathquill.cli --root /absolute/private/store --op publication-status --request incident_001
python3 -m pathquill.cli --root /absolute/private/store --op publication-reconcile --request incident_001 --epoch CURRENT_EPOCH
python3 -m pathquill.cli --root /absolute/private/store --op export-cancel --request incident_001 --epoch CURRENT_EPOCH
```

After diagnosing and repairing a storage/permission problem, reconciliation may
resume known cleanup. It never authorizes arbitrary deletion of mismatching data.
BLOCKED needs operator investigation; no force-delete or automatic repair of
unknown ownership is provided. Published artifacts and external reader leases
remain outside this slice.

## Reproduction and evidence

In the existing disposable Linux VM:

```sh
sudo timeout 85 unshare --net python3 tools/publication_recovery.py orchestrate
```

The runner seeds synthetic source data using the product API. It invokes the
formal daemon and subprocess CLI. A test-only wrapper calls the same formal
entry point, pausing immediately before/after the actual production rename, or
after a production cleanup unlink. The parent observes Linux stopped state,
checks the actual persistent ledger, then sends SIGKILL. No production fault
flags, alternate recorder or replacement filesystem backend are used. These are
deterministic boundary injections, not randomly timed crashes in an unmodified
launch or a test of failure inside the kernel rename syscall.

VM cases verify: after-rename adoption with unchanged file bytes/inodes/mtime;
second crash after one cleanup unlink with reservation unchanged and two files
remaining; unknown staging preserved; accepted cancellation surviving another
process restart. Actual CLI exit codes and old-epoch rejection are checked.
Source fingerprints and runner cleanup are retained in [JSON](../evidence/publication-recovery.json)
and [HTML](../evidence/publication-recovery.html). Restart-ready duration includes
process launch and successful CLI status observation, not an outage bound or
benchmark. It excludes later cancellation/stale-request checks. Final regression
runners may execute concurrently in separate namespaces within the same VM;
these durations are not isolated performance measurements.

Unit regressions additionally cover partial staged writes, altered/replaced
files, missing delivered packages across repeated restarts, cleanup fsync and
SQLite-commit failures, retained credit and repair. Those errors are injected;
they are not physical media failure or real disk-full cleanup qualification.
Existing publication, snapshot, capacity and live-network runners are refreshed
for the final source version, but their scopes remain separate.

No VM reboot, sudden power loss, zero-gap boot, external reader lease, automatic
published-artifact retention, production deployment or long-term qualification is
claimed. GitHub remains Private and no project license has been selected.
