> Historical exploration status for the sources recorded in these reports. For the current installed-service contract and bounded closeout, see [DEPLOYMENT.md](DEPLOYMENT.md) and [CLOSEOUT.md](CLOSEOUT.md).

# Continued technical explorations

The continuation-stage record is [continued.json](../evidence/continued.json), with the
same JSON escaped in [continued.html](../evidence/continued.html).
[reboot.json](../evidence/reboot.json) and [HTML](../evidence/reboot.html) cover
one normal VM reboot of that recorded core revision, not the latest daemon or
installed systemd service. Older exploration.json/html describe
the original revision only; their source fingerprints intentionally differ.

## Results and boundaries

- 22 identified tests exercise the actual Store, Recorder and RouteSocket code.
  Real unprivileged subscribed Netlink dumps collect link/address/route interval
  evidence with interleaved notifications. Interrupted dump and negative DONE
  cases are injected into the formal synchronize method; real kernel ENOBUFS
  and continuous churn are not qualified. Repeated synchronize calls rebuild
  dump interval evidence, not a linearizable materialized network-state view.
- Recorder commits a bounded rolling observation ring and copies existing
  observations into captures in the admission transaction. Later observations
  are copied into active captures. Retained captures survive ring eviction.
  AUTOINCREMENT prevents sequence reuse after all ring rows are reclaimed.
  Persisted pre-event data can be shorter than 60 seconds, especially after
  startup; coverage remains UNKNOWN rather than claiming completeness.
- A real loopback TCP listener produces success, closing it produces refusal,
  and a controlled UDP DNS server returns SERVFAIL. Actual Recorder probe
  methods trigger capture and retain pre/post observations. This is a narrow
  explicit DNS probe, not a general DNS resolver. A full asynchronous scheduler
  and automatic recovery/debounce are not qualified.
- The namespace runner mounts two dedicated 2 MiB tmpfs filesystems. Filling
  one until write returns ENOSPC prevents a Recorder observation commit, marks
  it degraded and rejects another incident. Removing filler and reopening
  permits a new commit. This is actual filesystem exhaustion in RAM-backed
  storage, not physical SSD failure or block-device corruption.
- Linux refused read-only remount while files were writable/open. The final
  test closes the recorder, remounts the real filesystem read-only, confirms
  startup refusal, remounts read-write and confirms repair. Running-service
  read-only behavior is only the earlier query_only injection; do not combine
  the two as one live remount test.
- Before normal VM reboot, the recorder commits a capture and observations and
  exits without sealing it. After boot ID changes, raw SQLite is inspected
  before Recorder construction: the row must still be CAPTURING. Recovery
  seals PARTIAL/restart, preserves capture count, rejects the old epoch and
  produces an allowlisted export. This excludes shutdown-time sealing as the
  explanation. It does not test systemd autostart or sudden power loss.

## Reproduce in disposable Linux VM

Run as a non-root user with UID 501 (the runner currently requires this explicit
fixture identity), Python 3.12+, sudo, iproute2, mount and unshare:

```sh
sudo unshare --mount --net --propagation private python3 tools/continued.py orchestrate evidence/continued.json
python3 tools/reboot.py prepare
sudo reboot
# After reconnecting, in the same checkout:
python3 tools/reboot.py after
```

The namespace runner has an outer 60-second worker timeout and finally unmounts
its filesystems. It creates dummy links only in its private network namespace.
Store roots must be private directories owned by the service account. Raw DB
and writer-lock files use mode 0600. The two tmpfs fixtures contain private
store subdirectories.

Its output is invalidated before starting, so topology/preflight failure cannot
reuse an old successful result. VM reboot intentionally interrupts the SSH call;
only the after-phase report proves success. Reboot state is stored under guest
/var/tmp and removed after successful verification. Failed runs retain it for
inspection; no certificates, raw dataset, secrets or guest state are committed.

## Remaining gates at this historical stage

A complete service still needs decoded/reconciled current-state snapshots,
continuous collection and event watermarks, bounded scheduling/recovery rules,
retention, robust export-file snapshot/publication and lifecycle cleanup.
The export at that stage includes trigger metadata and aliases, not an observation
HTML timeline. Its in-memory result does not qualify file-export/GC races.
All mutation paths need consistent degradation handling before service release;
legacy Store gap/finish/delete are not a full storage-failure interface.
No wall-clock-step, suspend, power-loss, prolonged overload, WAN, physical media
or long-term resource qualification is claimed. Current project license: [MIT](../LICENSE).

## Review corrections

The a097fb8 review found counterexamples missed by the initial 13 tests. The recorded continuation
regressions cover expired captures refusing late merges, total payload accounting
including incident bodies, delete reclaiming capture rows, reuse of same-boot
prebuffer across process restart, and rejection of public store directories.
Capacity counts payload bytes only; filesystem allocation is still measured
separately and is not a hard quota. Expired captures require explicit finish
before a new incident can be admitted; automatic lifecycle driving remains an
MVP gate.

Netlink NLMSG_OVERRUN now invalidates the dump before sequence routing. Dump
request sequences increase across synchronize calls; stale dump replies cannot
complete a later dump. Tests inject these controls into the formal backend;
actual kernel overrun remains untested. Synchronization still records interval
counts/notifications, not a complete decoded reconciled current-state view.

TCP rejects nonnumeric addresses before networking. DNS rejects truncated
resource records and non-query opcodes; malformed replies produce UNKNOWN and
cannot trigger a DNS-error incident. The real SERVFAIL test now uses a separate
Recorder and asserts creation of its own capture. This is not general DNS
protocol compatibility qualification.

Reboot tooling invalidates its old success before prepare/recovery preflight,
requires exactly stale_epoch rejection, compares runtime sources before/after
boot and hashes complete capture tuples rather than relying on counts alone.
Cleanup must finish before passed=true. The missing-pointer regression verifies
old success cannot survive a failed run. Normal reboot was repeated for these
sources; no sudden power-loss claim is made.
