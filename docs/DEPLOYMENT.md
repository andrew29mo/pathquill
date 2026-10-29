# Installed package and systemd lifecycle validation

The Linux service runs the installed Pathquill wheel as a dedicated non-root
account. This stage covers fresh installation paths, actual systemd lifecycle,
network namespace attribution, process-crash takeover, restart limiting and
SEALED-store termination. It does not qualify a clean OS installation, boot-time
enablement, VM reboot, power loss or long-term deployment.

## Fresh installation

Required: Linux with actual systemd as PID 1, Python 3.12+, Python venv/pip,
iproute2 and root privileges for installation. On the tested Ubuntu VM,
python3-venv supplies the required venv/pip tools. No Python runtime dependencies
are declared. Wheel building uses the pyproject build backend; build isolation
may download build tooling. Build logs/environment and the wheel hash belong in
your own deployment records; building is not an offline/reproducible-build claim.

```sh
python3 -m venv /absolute/build-environment
/absolute/build-environment/bin/python -m pip wheel --no-deps --wheel-dir /absolute/wheels /absolute/pathquill-checkout
sudo sh /absolute/pathquill-checkout/deploy/install.sh /absolute/wheels/pathquill-0.0.1-py3-none-any.whl
```

The installer refuses existing installation/config/data/unit paths, a loaded/vendor
unit, or an existing
pathquill user/group, rather than overwriting them. It is a fresh-install helper,
not an upgrade/uninstall/migration engine. Partial installation requires review;
there is no destructive automatic rollback of local files.

Paths and ownership:

| Item | Location / authority |
| --- | --- |
| Installed venv | /opt/pathquill/venv, root-owned |
| Configuration | /etc/pathquill/config.json, root:pathquill 0640; directory 0750 |
| State parent | /var/lib/pathquill, pathquill-owned 0700 |
| Default store/socket | /var/lib/pathquill/store, 0700; control.sock 0600 |
| Unit | /etc/systemd/system/pathquill.service, root-owned |

The initial configuration is an empty target list. Read-only network state is
still collected, but no active probe targets are configured. Review targets
before starting. Installation does not start or enable the service.

```sh
sudo systemctl start pathquill.service
sudo -u pathquill /opt/pathquill/venv/bin/python -I -m pathquill.cli --root /var/lib/pathquill/store --op status
sudo systemctl stop pathquill.service
```

CLI status contains private network observations and administrative identities;
do not share it as a sanitized public export. Operator access uses the service
account or an administrator; the socket is not made world/group accessible.

## Service authority and network scope

The exact shipped unit runs Python with -I, working directory /, and removes
PYTHONPATH/PYTHONHOME. There is no checkout-relative execution. Runtime receives
no Linux capabilities and sets NoNewPrivileges. Configuration and package files
are protected, with state writable under /var/lib/pathquill. Private temporary
and device views do not create a private network.

The normal unit intentionally inherits the host network namespace so read-only
Netlink collection and probes observe that namespace. Do not add PrivateNetwork
and then assume it still observes the host. No CAP_NET_ADMIN, route modification
or firewall management is part of this service. Configuration hardening is not
a promise that arbitrary untrusted targets or a compromised same-UID process are
safe; the existing private-store trust boundary remains.

In the VM suite, a separate declared NetworkNamespacePath drop-in targets an
isolated fixture for TCP/route/crash tests. The fixture has its own dummy link,
address, route and TCP listener; it changes no default VM route. The report
separates the normal VM namespace check from this explicit test namespace.
Neither check establishes external/WAN reachability.

## Stop, crash and restart policy

The shipped unit uses Restart=on-failure, RestartSec=1, a 30-second start-limit
window with burst 3, KillMode=control-group and TimeoutStopSec=8. Type=simple
means systemd active does not prove application readiness; query the private CLI
and require RECORDING for readiness. Slow/hung synchronous I/O can exceed normal
stop latency and cause systemd to force termination; graceful cleanup then cannot
be assumed. These are configured policies, not universal recovery-time bounds.

Normal SIGTERM/stop waits for bounded probe workers, closes its Netlink/RPC
sockets and releases the writer lock. The service has threads, not detached
writer subprocesses. A crash can leave a socket pathname until the next
instance takes the lock and replaces it. Startup uses the same recovery logic
already documented for exports and publication cleanup.

SEALED has dedicated exit status 78. The unit treats it as a successful permanent
stop and also lists it in RestartPreventExitStatus. Ordinary failures retain
on-failure/rate-limited behavior. An ExecStopPost helper emits a small private allowlisted exit receipt from
systemd-provided SERVICE_RESULT/EXIT_CODE/EXIT_STATUS/INVOCATION_ID. It does not
write the store or dump arbitrary environment variables. It runs under the same
service account and restrictions. This retains exit-code evidence even after
systemd garbage-collects an inactive unit. A normal store-seal returns over the established
connection, removes the socket before durable sealing and exits normally. An
explicit later start on the sealed root exits 78 without reopening recorder
writes or entering an automatic restart loop. Use the separate archive/new-store
workflow and explicitly review the service root/configuration for a new store;
no automatic rollover or service reconfiguration is added.

When a real startup error reaches the start limit, diagnose and repair it first,
then systemctl reset-failed and start. Do not disable the limit to hide the error.
The VM validation uses an invalid probe port to produce repeatable failed starts,
then repairs configuration and verifies normal operation returns.

## Reproduce the actual-systemd evidence

Run only in a disposable Linux VM with no existing Pathquill installation:

```sh
sudo timeout 300 python3 tools/deployment.py orchestrate
```

The orchestrator requires real systemd, refuses pre-existing paths/account/unit,
builds a wheel from copied fingerprinted source, checks every wheel module against
source and installs using deploy/install.sh. An isolated interpreter at cwd /
then requires a site-packages origin and checks all installed module hashes.
The actual service uses that interpreter/module; its command line, working
directory, environment, UID, capabilities and network namespace are inspected.
The original unit is byte-compared to the shipped unit and verified by systemd.
A repeated install is refused without replacing configuration. Source unit tests
run separately; matching fingerprints bind the installed code
to that tested source. This is not a claim that every unit test ran from the wheel.

The suite tests:

- Default VM network namespace and independent ip link-name comparison; non-root
  UID, zero effective capabilities, NoNewPrivileges and private store/socket.
- Normal stop, empty service cgroup, removed socket and finite no-restart check.
- Explicit namespace with independently observed fixture interface/route and
  successful TCP probe. Actual SIGKILL must produce a new PID/invocation/epoch,
  increased restart count, interrupted old export, released owned hold and old
  operation rejection through installed CLI.
- Current-test PID 1 start-limit journal evidence, exact configured number of
  starts, stopped restart count, repair/reset. This systemd 255 retains
  Result=exit-code at the limit; that field alone is not treated as proof.
- Normal sealing and explicit sealed-root start with status 78 and no restart.
  Same-boot/current-phase manager starts, the store_sealed message and the
  matching invocation exit receipt are required; the sealed DB hash is unchanged.

[JSON](../evidence/deployment.json) and [HTML](../evidence/deployment.html) contain
the same results, wheel/install provenance and source fingerprints. Failed
attempts are retained in evidence/deployment-attempts; they are not passing
qualification. Timing is a finite observed interval from kill request to a
successful new-epoch CLI response, not an outage/SLA bound. Memory fields are
Linux-VM service observations: main-process VmRSS and cgroup MemoryCurrent are
different quantities and are not compared to native macOS RSS or treated as a
leak test. Other regression runners may share the VM during final verification;
these are not isolated performance measurements.

Negative validator tests reject prior boots/times, foreign units, application
messages posing as manager records, missing limit events, wrong start counts
and mismatched exit invocations. UUID spellings are normalized before comparing
/proc boot identity with journal identity. Inactive-unit reset-failed may report
not-loaded; it is tolerated only when already inactive with no main process,
never as a substitute for failed-service repair.

Invalid invocation invalidates prior success. SIGTERM of the orchestrator enters
its cleanup path; a forced SIGKILL of the orchestrator or uninterruptible kernel
I/O cannot promise automatic cleanup and is not qualified by this suite.

Parent supervision bounds workers and stops the real systemd service during
cleanup even though it belongs to PID 1 rather than the worker process group.
This suite removes only its fresh fixture installation/account/namespace;
prerequisite OS packages remain installed. It does not enable boot startup or
reboot/stop the shared VM. Raw private VM network state/journal is not committed.

Remaining acceptance is a separate clean-VM document-driven full workflow and
bounded sustained-operation run. No VM reboot, power loss, zero-gap boot,
automatic upgrade, native macOS daemon support or production guarantee is claimed.
GitHub stays Private and no project license has been selected.
