# Explicit export retirement and full-history handoff

This slice adds operator-requested retirement, safe deletion/recovery, and an
explicit workflow after the 32 export-history slots are full. It does not add
automatic TTL deletion, history rollover, reader leases or formal deployment.

## Retire a published package

Copy the whole package to a user-managed destination and verify its manifest
before requesting retirement when a copy must be retained. This is an operator
responsibility; the CLI cannot prove an external copy exists. Direct concurrent
filesystem readers are not
tracked: a reader opening another file during deletion may fail; an already open
Unix file may remain readable after unlink. Retirement is not secure erasure,
revocation of copies, or proof that physical blocks have been freed.

```sh
python3 -m pathquill.cli --root /absolute/private/store --op status
python3 -m pathquill.cli --root /absolute/private/store --op publication-retire --request incident_001 --package PACKAGE_ID --store STORE_ID --epoch CURRENT_EPOCH
python3 -m pathquill.cli --root /absolute/private/store --op publication-status --request incident_001
```

Retirement requires current store identity, epoch, request ID and exact opaque
package ID. It verifies the complete published package against the fixed snapshot
and captures directory and file identities/content in a durable retirement
inventory before deleting anything. Unknown/extra/replaced content is preserved
and BLOCKED. A mismatched package/store or old epoch cannot authorize deletion.

```text
PUBLISHED --explicit retire--> RETIRE_PENDING --> CLEANED (outcome RETIRED)
                                  |-------> BLOCKED --safe reconcile--> RETIRE_PENDING
```

The same single writer and bounded cleanup scheduler removes at most one known
file per turn, syncs its directory, then removes the empty directory and syncs
packages. Only the final SQLite transaction sets publication bytes to zero and
removes the snapshot bytes, marking the export RETIRED. Until then all original
credit remains reserved and unresolved cleanup blocks new publication. A missing
file is tolerated only after a persisted retirement inventory authorizes its
deletion. A crash after unlink or directory removal can resume after restart.
No source incident or source hold is released by this operation.

Repeated retirement returns the existing progress/terminal result, never republishes
or restarts deletion under a reused history slot. Cancellation cannot turn an
accepted retirement into ordinary interrupted-publication cleanup. Retired IDs
remain in the 32-row history; repeating the original export request returns its
terminal result. Republishing it is refused. Filesystem/SQLite errors do not
report deletion complete or free credit early; unknown layouts require review.

## Understand the limits

Administrative status now includes stable store_id and lifecycle, plus:

- capacity.export_history: used / limit / remaining (32 slots per store).
- capacity.snapshots: logical stored snapshot bytes / 1 MiB.
- capacity.publications: logical reserved package bytes / 4 MiB.

Retirement releases the relevant file/snapshot credit, not the request-history
slot. SQLite pages need not shrink after NULL/deletion; journals/pages are not
securely erased. Unlinked files held by external readers may still occupy blocks.
Unknown on-disk bytes remain part of publication admission accounting. This is
not a global filesystem quota across manually retained stores.

The 33rd new request returns export_history_full without deleting history.
Existing read/status, retirement, reconciliation and sealing remain available.
There is no hidden truncate, automatic rollover or same-path reset.

## Seal, archive in place, create a fresh store

1. Finish captures, release user holds, cancel/finish pending exports, and resolve
   cleanup. Retain published packages or explicitly retire them first.
2. Save the store_id and current epoch from status. Seal using both. The daemon
   refuses active captures/references/exports, unresolved publications and pending
   probes. If probes are in flight, retry during an idle interval; this is not a
   new pause/drain interface.
3. The daemon removes its socket before committing SEALED, sends its result over
   the already established connection and exits. No recorder writes run after
   that commit. A crash before commit can restart the OPEN store; after commit,
   startup refuses store_sealed. There is no unseal API. A lost reply can be
   assessed using the offline archive operation with the previously saved ID.
4. After the process exits, create an integrity receipt in the sealed directory.
   The offline CLI holds the same writer lock, requires SEALED and matching
   identity, checks SQLite quick_check and known published contents, and refuses
   unknown entries. It preserves all original raw data/history in place.
5. Explicitly create a different, non-existing store path using that archive.
   It requires no pending archive receipt and validates the completed receipt
   again, creates an independent store ID and records
   parent_store for local provenance. It copies no sources, requests or references.
6. Start the daemon on the new root and use its fresh status/epoch. Update any
   future service configuration explicitly; automatic service reconfiguration
   is not part of this slice.

```sh
python3 -m pathquill.cli --root /absolute/private/old-store --op store-seal --store OLD_STORE_ID --epoch CURRENT_EPOCH
# Wait for daemon exit. These operations are offline:
python3 -m pathquill.cli --root /absolute/private/old-store --op store-archive --store OLD_STORE_ID
python3 -m pathquill.cli --root /absolute/private/new-store --op store-new --archive /absolute/private/old-store --store OLD_STORE_ID
python3 -m pathquill.daemon --root /absolute/private/new-store --config /absolute/private/config.json
```

Parent directories must already exist; old and new roots must be absolute,
distinct and not nested. Existing destinations are refused. Do not delete or
rename the old root to reuse its path: that bypasses the documented identity
boundary. No automatic reclaim of sealed archives is provided.

A new store has 32 empty history slots and a new runtime epoch. Captured old
requests containing the previous epoch are rejected; supplied old store identity
is also rejected. Retirement and sealing require an explicit store identity;
legacy export calls still require epoch and may optionally bind store_id through
--store. Request names are scoped to a store, not a global deduplication service:
manually authorizing a new request with a new source/current identity/current
epoch is new work even if its display ID matches one in a different archive.

## What the archive does and does not guarantee

archive.json is a private integrity receipt containing store ID, history count
and hashes/lengths for the database and known packages. It is atomically linked
from a synced private pending file, without overwrite, and the parent is synced.
Retry resyncs existing complete receipts. Complete pending receipt publication
can finish on retry; partial/mismatching pending data is preserved and refused,
not overwritten. A new-store initialization failure may leave a partial new root;
retry never overwrites it. Inspect it and choose a different path after review.

The receipt is not an independent backup, a signature or protection against an
administrator changing both data and receipt. It does not enforce OS-level
read-only storage. Product entry points reject sealed stores; an administrator
can still alter local files outside the product. Keep the whole archive private:
it contains original network observations and administrative identifiers, unlike
the sanitized public export package. Do not upload the archive/receipt as a
public diagnostic artifact.

Unknown root/package entries are preserved and block archiving; inspect and
preserve them separately before retrying. No force-delete option is provided.
No copying of a potentially live SQLite database is used in this workflow.

## Reproduce and assess evidence

In a disposable Linux VM:

```sh
sudo timeout 85 unshare --net python3 tools/retention.py orchestrate
```

The runner uses actual daemon entry points and subprocess CLI. It seeds synthetic
sealed sources through the product API, then verifies:

- Retirement interrupted by SIGKILL after the real unlink, with two files and full
  reservation remaining; process restart completes deletion without replay.
- Unknown published data is preserved and deletion refused.
- SIGKILL after the real seal commit but before its reply: the socket is already
  removed and offline archiving succeeds without reopening the sealed store.
- 32 export/cancel pairs through the CLI, rejection of the 33rd, normal sealing
  and exit, sealed-startup rejection with unchanged database bytes, idempotent
  archive receipt, explicit new store, old store/epoch/source rejection, and new
  work accepted under the new namespace. The old 32-row database stays unchanged.

The test-only wrapper pauses at production unlink/seal boundaries before the
parent sends actual SIGKILL. No alternate recorder/backend or production fault
flags are introduced. Unit tests additionally inject final SQLite/sync failures,
unknown pending receipts and wrong authority. They are not physical disk-failure
or power-loss experiments. [JSON](../evidence/retention.json) and
[HTML](../evidence/retention.html) retain the same results and source fingerprints;
other runners are refreshed for the same final runtime with their own scopes.

No VM reboot, sudden power loss, zero-gap boot, kernel short-write, long-term
rollover, independent backup restore, reader-lease safety or formal systemd
installation qualification is claimed. GitHub stays Private, with no license
selected. mvp_qualified remains false until the separate deployment acceptance.

## Retirement-stage review corrections

Retirement verification now checks both package reservation and the actual
snapshot bytes/digest during the stopped first-unlink boundary, and requires both
credits to be released only after completion. The final-transaction SQLite-failure
regression also requires the original snapshot to remain readable and charged.

Fresh-store handoff now rejects an existing .archive.pending even alongside a
valid receipt, creating no destination and preserving pending bytes. Run
store-archive to reconcile a known complete linked pending receipt; mismatching
pending data still requires operator investigation. The VM fixture verifies a
structured handoff refusal and preservation, then explicitly removes only its
own injected marker before continuing; that removal is not product behavior.
Old archive paths must be absolute before canonical path checks. Tests also
require the created store identity to survive reopening and rejected old requests
to leave its fresh history empty. No global cross-store deduplication is implied.
