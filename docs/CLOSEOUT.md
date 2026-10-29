# Bounded Linux MVP closeout

This acceptance uses a newly created Colima Linux VM profile, with no prior
Pathquill account, installation, configuration or store. It is an Ubuntu 24.04.4
minimal **Colima containerd image**, not a pristine upstream Ubuntu installation
or a hardened production host. Containerd is part of the image; Pathquill runs
as an actual systemd service, not a container.

## Install according to the documented contract

The new VM initially had Python 3.12, systemd and iproute2, but lacked Python
venv support and package indexes. On this image the prerequisites are:

```sh
sudo apt-get update
sudo apt-get install -y python3-venv
```

Then follow the wheel build, `deploy/install.sh`, systemctl and installed CLI
steps in [DEPLOYMENT.md](DEPLOYMENT.md). The installer fixes its umask to 022;
configuration and state retain explicit private modes. Qualification runs install
under caller umask 077 (closeout) and 000 (deployment), require root-owned package
files without group/world write permission, and execute as the actual service
account. This addresses both unreadable installs and writable-code installs.

For a newly provisioned disposable VM, record the absence checks and boot-bound
pre-install receipt `/run/pathquill-clean-vm.json` before installing Pathquill.
The committed report records that receipt, OS/runtime, installed wheel digest,
every installed module digest, exact unit comparison, and tested source hashes.
The receipt is a test provenance record, not remote attestation: a root operator
can fabricate it. Freshness of the VM is established by the separate VM creation
step, not inferred from an empty application directory alone.

```sh
sudo timeout 650 python3 tools/deployment.py orchestrate-closeout
```

The closeout mode shares the production installer and supervised ownership-based
cleanup with deployment validation. It requires actual systemd as PID 1, no
pre-existing Pathquill paths/account/loaded unit, and a receipt from this boot.
The complete VM creation/prerequisite sequence is described below. Repeated
application attempts on this newly provisioned VM must be identified as such;
passing a later attempt does not erase failures.

## Fresh VM preparation recipe

Use a new empty private COLIMA_HOME and a unique unused profile; do not reuse or
stop another project's VM. The measured profile used 2 CPUs and 2 GiB RAM with
VZ/aarch64. Substitute absolute paths and keep the checkout mounted only for
building/testing and writing evidence:

```sh
mkdir -p /absolute/private/colima-closeout
export COLIMA_HOME=/absolute/private/colima-closeout
colima start closeout --cpu 2 --memory 2 --disk 10 --root-disk 10 --vm-type vz --runtime containerd --activate=false --ssh-config=false --mount /absolute/pathquill-checkout:w
colima -p closeout ssh
```

Inside that newly created VM, install the prerequisites above, then create the
boot-bound receipt **before** the first application install:

```sh
sudo python3 - <<'PYRECEIPT'
import hashlib,json,os,pathlib,platform,subprocess,time
p=pathlib.Path('/run/pathquill-clean-vm.json')
assert not p.exists()
paths=['/opt/pathquill','/etc/pathquill','/var/lib/pathquill',
       '/etc/systemd/system/pathquill.service',
       '/etc/systemd/system/pathquill.service.d']
assert not any(os.path.lexists(x) for x in paths)
for kind in ('passwd','group'):
    assert subprocess.run(['getent',kind,'pathquill'],capture_output=True).returncode!=0
assert subprocess.check_output(['systemctl','show','pathquill.service',
    '--property=LoadState','--value'],text=True).strip()=='not-found'
p.write_text(json.dumps(dict(schema='pathquill-clean-vm-v1',application_absent=True,
    base='New official Colima Ubuntu 24.04.4 minimal containerd image',
    python=platform.python_version(),monotonic=time.monotonic(),
    boot_sha256=hashlib.sha256(pathlib.Path('/proc/sys/kernel/random/boot_id').read_bytes()).hexdigest(),
    prerequisites='apt-get update; apt-get install -y python3-venv',
    not_pristine_upstream_ubuntu=True)))
PYRECEIPT
cd /absolute/pathquill-checkout
sudo timeout 650 python3 tools/deployment.py orchestrate-closeout
```

The runner builds and installs with the documented commands and uses the same
CLI/module entry points. It adds only the declared namespace fixture, workload
assertions, provenance, supervision and cleanup. After reviewing reports, stop
only the disposable profile you created with `colima stop closeout`; do not
assume the runner shuts down the VM or removes prerequisite packages.

## Fixed workload and acceptance

The resource acceptance is fixed in `tools/closeout_checks.py` before measurement:

| Item | Acceptance |
| --- | --- |
| Observation | At least 300 seconds and 6 real fault/recovery/export/retire cycles |
| Sampling | Every approximately 2 seconds; no gap above 6 seconds |
| Warmup | First 45 seconds excluded only from RSS/FD/thread span comparisons |
| Service identity | Same MainPID, invocation and epoch throughout; NRestarts = 0 |
| RSS | Warmed span <= 8 MiB; last/first 10 warmed-sample median growth <= 2 MiB |
| File descriptors | Warmed max-min <= 4 |
| Threads | Warmed max-min = 0 |
| Store allocation | All samples <= 24 MiB (sum of files' st_blocks * 512) |

These finite gates catch gross growth for this workload. They are not evidence
of indefinite memory stability, filesystem quotas or long-term rollover. Every
sample is retained; failed checks fail the report. Resource validator unit tests
reject short runs, missing sample intervals, service identity changes, restart
counts and each exceeded resource threshold. The store retains bounded history plus the latest raw incident; increasing disk bytes are reported, not called a
leak or hidden by deleting history.

The same unmodified installed daemon runs under systemd in an explicitly isolated
network namespace. A TCP fixture is stopped/restarted to create actual failed
probes, captures, restored health and 30-second committed sealing. The service
itself is not restarted during the resource observation. Each cycle uses the
installed CLI to request a fixed snapshot, publish JSON/HTML, verify an operator
copy against the manifest, repeat publication without rewriting, and explicitly
retire it. Raw fixture IP/interface values must be absent from all package files.
No synthetic incident is seeded and no production method is monkeypatched.
After the next cycle is copied and retired, an explicit CLI delete reclaims the
previous raw incident; the latest source remains for the history-full check.
This is operator-directed raw-data deletion, not automatic retention expiry or
history-slot reclamation. Each export must contain a SEALED/recovered incident,
a TCP failure near its trigger time and a later success in order. Counts and
relative times are retained, alongside negative validator tests for missing
trigger/recovery observations.

After observation is complete, the remaining export-history slots are filled
through CLI export/cancel. Request 33 must return export_history_full; no history
is deleted. Only **after** the resource observation does an explicit service
stop/config edit/start remove probe targets so sealing can occur while idle.
The workflow rejects an old epoch, seals the store, creates an in-place archive
receipt, initializes a distinct new store, then explicitly changes the unit root
and starts it. The new store has a different identity and empty history; old
store authority is rejected and the sealed old database remains byte-identical.
This manual handoff does not claim automatic rollover.

## Measurement and cleanup boundaries

Main-process VmRSS, FD and thread count come from /proc. Logical store size and
allocated file bytes are separate. Directory enumeration is not atomic; a
transient SQLite DELETE-journal can disappear while sampled. Samples skip a
vanished file and are observations, not physical-disk peak or hard quota claims.
CLI polling and copy verification are included in the workload. No comparison
against native macOS memory, isolated microbenchmark throughput, p99 latency or
SLA is made.

Both orchestrator modes require successful systemctl stop, no main process,
inactive/failed state and an empty prior service cgroup before removing owned
installation paths/account. Cleanup failure preserves the installation and fails
the report. The VM's prerequisite packages remain; the host's other VM is not
stopped or modified. Raw stores, private network status and journal are not
committed. Reports are JSON/HTML representations of identical result objects.

No service boot enablement, service VM-reboot recovery, abrupt power loss,
zero-gap boot, external-reader lease safety, automatic upgrades or production
qualification is established by this closeout. Earlier reboot experiments have
their own narrower scope and must not be substituted for this service test.
GitHub is now Public and the project now uses [MIT](../LICENSE).

## Failed attempts and the progress correction

The first attempt timed out during snapshot readiness. A diagnostic rerun
confirmed cycle_2 reached FAILED with 4,150 capture rows, above the unchanged
4,096-row export-input limit; control loss/refusal counters remained zero.
Two preceding snapshots were successfully exported and retired. Both failed
attempts are retained in evidence/closeout-attempts. The later attempt uses the
same newly created VM after the owned application paths/account were cleaned;
it must not be described as the first application attempt succeeding.

The daemon previously committed redundant idle progress every 20ms loop turn.
Progress commits now coalesce at 100ms; select/probe/network-event handling is
not slowed to 100ms. Notifications still drain first; sealing still requires an
actual durable progress watermark beyond the capture deadline. This fits this
small TCP workflow within existing row/snapshot limits without raising budgets.
High event rates/extended captures may still correctly exceed those limits and
fail export. Bounded failure remains part of the contract, not general export
completeness under arbitrary load.

## Final observed results

The final same-source run passed and completed cleanup. Seven regression flows
(deployment, retention, publication recovery, publication, snapshot, capacity and
milestone 1) also passed with 111 distinct source tests each. Their current
runtime/test fingerprints match this checkout; installed-module hashes match
those production source bytes. These are repeated executions of the same 111
tests, not 777 different tests.

| Observation | Final result |
| --- | --- |
| Continuous same-service observation | 329.93 seconds (about 330 seconds) |
| Complete real fault/recovery/export/retire cycles | 9 |
| Resource samples | 161 |
| Service identity | One PID/invocation/epoch; zero restarts |
| Warmed main-process RSS | 20860–21888 KiB (about 20.4–21.4 MiB) |
| RSS last/first warmed 10-sample median growth | 872 KiB |
| File descriptors | 7–8 |
| Threads | 2–2 |
| Maximum sampled allocated store bytes | 786432 bytes (768 KiB) |
| History-full and handoff | Request 33 refused; seal/archive/new store completed; old authority rejected |
| Orchestrator cleanup | Passed |

[Final JSON](../evidence/closeout.json) / [HTML](../evidence/closeout.html) retain
identical data. The first passing observation is also retained in
evidence/closeout-attempts, alongside both failures. Its product bytes match the
final product, but its runner fingerprints predate the final sample-freeze and
validation checks; it does not substitute for this final run.

This completes the planned **bounded Linux functional closeout**. Individual
slice reports keep their conservative mvp_qualified=false field; the completion
statement here is based on the combined current passing flows, not on one slice
being a blanket qualification. No long-term stability or production guarantee is
added. Full source tests require Linux /proc and are not claimed as native macOS
service qualification. GitHub is now Public and the project now uses [MIT](../LICENSE).
