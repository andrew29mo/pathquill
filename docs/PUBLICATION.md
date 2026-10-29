# Fixed package publication (P0-4a / P0-4b, extended by P0-4c)

The formal daemon uses PublicationRecorder, extending ExportRecorder. An explicit
`export-publish` operation publishes the existing sanitized SQLite snapshot as a
private on-disk package. Publication does not reread source incidents or acquire
new source references. Source GC remains independent after SNAPSHOT_READY.

P0-4c now adds [restart reconciliation and cleanup](PUBLICATION_RECOVERY.md).
The publication contract below remains the foundation.

## Contract and cancellation

The existing export request ID also identifies its single publication. The
snapshot schema and package schema are fixed; callers cannot provide paths,
filenames, render templates or output options. Repeating successful publication
returns the original package/status without rewriting files or extending time.
The original export boot/deadline applies to first publication; a same-boot
restart does not renew it. An unpublished snapshot from a previous boot cannot
be newly published. Successful results remain queryable after the deadline.
All mutation requests require the current writer epoch.

```text
SNAPSHOT_READY --export-publish--> PREPARING --> PUBLISHED
                                      \--> BLOCKED / CLEANUP_PENDING --> CLEANED
SNAPSHOT_READY --export-cancel--> CANCELLED (publication refused)
```

PREPARING is a durable publication intent written before filesystem work. The
single writer serializes publish and cancel. Cancellation processed before
publication removes the snapshot and prevents publication. Once PUBLISHED,
export-cancel refuses with already_published and does not erase files or the
snapshot. Cancellation of an interrupted publication first reconciles its files: a valid
final refuses as already_published; known unpublished work enters durable
CLEANUP_PENDING with outcome CANCELLED. Unknown layouts remain BLOCKED. Retry
never restarts interrupted/cleaned publication under the old request ID. No published-artifact deletion API exists
in this slice. A cancel queued during synchronous publication can run only after
that operation; there is no interruptible I/O or bounded cancellation latency.
The deadline is checked before work and immediately before rename; blocking
I/O/commit can cross it. This is not a hard delivery-time bound.

## Filesystem boundary

Under the already private recorder root, `packages` must be an owned directory
with no group/other permissions. Each package has an opaque random name and
contains exactly snapshot.json, index.html and manifest.json. Files are mode
0600; directories 0700. JSON is the exact fixed snapshot text. HTML escapes that
text. The manifest contains only schema, byte lengths and SHA-256 of JSON/HTML;
it is consistency evidence, not a signature or publisher authentication.

The writer persists intent/reservation, creates a private `.stage-<opaque>`
directory on the same filesystem, writes files exclusively, flushes/fsyncs them,
rereads/compares bytes and fsyncs the staging directory. Linux renameat2 with
RENAME_NOREPLACE then publishes the whole directory, refusing even an existing
empty destination. There is no check-then-os.rename fallback. The parent
directory is fsynced before SQLite records PUBLISHED and the CLI reports success.
Unsupported platforms/filesystems fail closed. This is namespace atomicity for
a complete package, not a single transaction across SQLite and the filesystem.

A crash or error after rename can leave a complete visible package without a
successful reply. Unknown or mismatched completion is BLOCKED, not silently retried or called
success. Restart and explicit reconciliation can adopt a verified complete final
or authorize cleanup of known staging. Cleanup is bounded and restartable;
published-artifact deletion remains deferred. Keep the private store inaccessible to other users. Malicious same-UID
modification and an administrator replacing files concurrently are outside this
trust boundary; this is not an untrusted shared output directory.

## Budgets and errors

One package is at most 2 MiB; all staging and final regular-file lengths count
toward a 4 MiB file-byte budget, with at most 32 package/staging directories.
These are separate from the existing 1 MiB SQLite snapshot and 32 request-history
limits. Admission checks budget before creating intent/files, never deletes old
packages to make room, and does not follow symlinks or accept nested directories
or multiply linked files during accounting. Unexpected entry types/counts refuse admission; other regular-file bytes still count.
Logical lengths exclude allocated blocks, filesystem metadata and SQLite size;
these limits are not disk quotas or guaranteed capacity reservations against
other programs. Published files/history are not automatically reclaimed. Interrupted staging
retains its full reserved bytes until cleanup and its final DB transaction
complete; unresolved cleanup blocks new publication.

Before intent, directory creation/accounting I/O failures return the fixed
publication_unavailable error without a publication record; repair permits retry
within the original deadline. After intent, write/sync/rename failures retain
intent, bytes and any owned files as BLOCKED, return publication_incomplete,
and prevent further publication.
SQLite failure may instead safely exit the daemon under the existing storage
contract; it cannot return a successful publication reply. Known interrupted
staging can now be cleaned through P0-4c; unknown data requires operator review. The read-only snapshot can remain available; do not
manually delete files and assume that also reconciles the ledger.

## CLI and evidence

After obtaining SNAPSHOT_READY through the existing export workflow:

```sh
python3 -m pathquill.cli --root /absolute/private/store --op export-publish --request incident_001 --epoch CURRENT_EPOCH
python3 -m pathquill.cli --root /absolute/private/store --op publication-status --request incident_001
```

The returned package ID locates `STORE/packages/ID`. Administrative RPC replies
still contain private daemon status and must not themselves be shared. Only the
three package files follow the sanitized export contract. Topology/timing may
still identify a system indirectly; this is not complete anonymity.

In a disposable Linux VM:

```sh
sudo timeout 55 unshare --net python3 tools/publication.py orchestrate
```

The runner uses the actual daemon and subprocess CLI, checks CLI exit codes,
manifest hashes/lengths, fixed-byte retry, cancel-before/after publication,
sensitive strings in filenames/content, and actual directory write denial.
Unit tests additionally challenge an existing empty destination, complete files
before rename, byte/entry limits, symlink refusal, deadline/epoch rejection,
injected fsync ENOSPC, post-rename EIO/SQLite failure, and conservative restart blocking.
The injected errors are not physical disk faults. Positive alias relationships
remain covered by snapshot tests. No overwrite is tested directly against the
production no-replace primitive, not inferred from random names alone.

[JSON](../evidence/publication.json) and [HTML](../evidence/publication.html)
contain the same observations and source fingerprints. CLI duration includes
client startup and IPC; it is one controlled observation, not a benchmark or
latency guarantee. The parent invalidates old success, bounds worker execution
and publishes the final verification report only after group cleanup. These
verification reports are distinct from product packages.

Before/after-rename and cleanup process-crash evidence is now documented in
PUBLICATION_RECOVERY.md. No crash inside the kernel rename operation, external-
reader lease, VM reboot, power-loss durability, zero-gap boot or long-term
qualification is claimed. GitHub remains Private; no project license is selected.

## P0-4a/b review corrections

Pre-intent directory creation/accounting I/O errors now return the path-free
publication_unavailable error through the formal RPC/CLI. No publication intent
or payload files are created in this branch (an empty packages directory may
exist); after repair the same request may retry against its original snapshot
and deadline. This differs from publication_incomplete after intent, which
remains conservatively BLOCKED until checked by reconciliation. Directory creation ENOSPC is unit-injected;
the VM exercises an actual unreadable package directory and repair with the
formal daemon/CLI. Neither is a physical media-failure qualification.

Package acceptance now compares JSON bytes/digest and escaped HTML against the
fixed snapshot API, requires the manifest schema and exact JSON/HTML members,
and positively requires useful sanitized fixture content. An empty self-consistent
package cannot pass solely by omitting sensitive strings. Regressions also
exercise expiry after staging (no final name) and a destination collision through
the full publication method, preserving the prior destination unchanged.
Those P0-4a/b review additions did not themselves qualify crash recovery or
automated cleanup; subsequent P0-4c evidence is documented separately.
