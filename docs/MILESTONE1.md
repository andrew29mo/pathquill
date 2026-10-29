# Milestone 1: live reconstruction and daemon

The formal implementation is `pathquill.daemon`, invoked with a private root and
JSON target configuration. It uses the existing Recorder/Store, not a test-only
writer. All SQLite operations occur on its owner thread. Workers perform bounded
numeric-IP TCP or explicit IPv4 UDP DNS operations and return outcomes only.

```sh
python3 -m pathquill.daemon --root /absolute/private/store --config /absolute/targets.json
python3 -m pathquill.cli --root /absolute/private/store
python3 -m pathquill.cli --root /absolute/private/store --resync
```

Example config (at most eight targets, 16 KiB config):

```json
[{"kind":"tcp","host":"127.0.0.1","port":8080,"timeout":1.5,"interval":5}]
```

Each target has one outstanding operation; timeouts are 0.05–2 seconds and
intervals 0.1–60 seconds after completion. There is no catch-up backlog. IPv6
numeric TCP endpoints are supported by the socket implementation but this
milestone's real probe fixture is IPv4. DNS is the narrow validated query from
the prior exploration; malformed/unknown results cannot trigger DNS-error or
restore health. The daemon/CLI share a private Unix socket; no remote API exists.

## State contract

A subscribed RouteSocket obtains bounded link/address/route dumps. State decodes
fixed headers and retains attributes as numeric keys/hex, excluding volatile
address/route cache metadata and irrelevant link statistics. Link identity uses
ifindex; a rebuild replaces the entire previous view so deletion and index reuse
do not retain old rows. This is a supported state projection, not a decoder of
every Linux link feature or nested routing attribute.

Decoded state objects are committed as observations with their generation; a
following sync record marks completion of that sampled projection. A crash
between records does not turn a partial sample into complete coverage.

A rebuild publishes only after two equal dump projections without interleaved
notifications. Up to three rounds are attempted; interruption, loss, decoding
failure or ongoing notifications prevent publication. The previous view and
health are invalidated when generation changes. The daemon retries DEGRADED
reconstruction at bounded intervals and reconstructs after notifications rather
than applying an unsafe notification replay over a non-atomic dump.

This converges after the topology becomes quiet; it does not promise atomic
cross-table observations, instantaneous freshness, or convergence under arbitrary
continuous churn. Independent VM checks compare link IDs/names and complete
address tuples against `ip -j`; route **counts**, not every route attribute, are
independently compared. Kernel loss/churn controls are injected in unit tests;
no real ENOBUFS qualification is claimed.

## Commit and incident lifecycle

Each worker result carries its launch generation. Results from prior generations
are discarded before touching health or incident state. Failure triggers/merges
a capture only while its window is open. UNKNOWN does not restore health.
Recovery requires current-generation success for every configured target.

The owner thread handles received notifications and completed results, then
commits a progress observation only when the socket is not currently readable.
Its persisted observation timestamp/sequence drives sealing. No CLI operation
accepts a caller-provided watermark. Sealing waits for outstanding probes, and
new probes are temporarily withheld for an expired capture so completion cannot
be postponed indefinitely by continuous scheduling. Capture contents still
reflect completion-time observations; kernel delivery gaps are not thereby
proved absent. Coverage remains UNKNOWN/PARTIAL rather than claiming COMPLETE.

SIGTERM stops the loop, waits for bounded workers, closes backend/DB and removes
the private socket. Pending captures retain the existing restart semantics.
Storage/admission errors fail the daemon closed; a production degraded-control
interface and comprehensive mutation recovery remain later milestones.

## Actual evidence

[JSON](../evidence/milestone1.json) and [HTML](../evidence/milestone1.html) bind
runtime, tests, producer and packaging fingerprints. The fixture starts the real
daemon processes and calls the real Unix client inside a dedicated Linux VM
network namespace, drops to UID 501, and uses no alternate implementation.

```sh
sudo timeout 75 unshare --net python3 tools/milestone1.py
```

The fixture runs all identified tests, changes real interface addresses during
bounded slow TCP work, requests resynchronization and observes stale-result
rejection, then checks deletion and the independent state projections. A separate
one-target daemon experiences a real refused connection and subsequent success;
it seals recovered after the real 30-second observation window using writer
commits. Another daemon independently captures real DNS SERVFAIL. Graceful exit
and socket cleanup are checked. This is controlled integration evidence, not a
WAN latency benchmark, leak test or systemd deployment qualification.

## Remaining gates

Capacity/retention and export-file ownership/publication remain milestone 2.
Formal systemd packaging, clean installation, daemon VM reboot/autostart and
bounded continuous-resource observation remain the deployment milestone. The
prior normal reboot evidence applies to its recorded exploration sources, not
this new daemon revision. No power loss, suspend or boot-zero-gap claim is made.
