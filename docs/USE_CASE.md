# A TCP failure, a shareable incident package, and a full store

This walkthrough uses Pathquill to record one local TCP service becoming
unreachable, retain context through recovery, produce a deidentified package,
and reclaim data without silently reusing request history. It ends by sealing a
full store and explicitly starting a new one. No application feature is added.

## What you need

Use a disposable **Linux VM with real systemd as PID 1**, Python 3.12+, venv/pip,
iproute2, sudo and network-namespace support. On the tested Ubuntu 24.04 VM:

```sh
sudo apt-get update
sudo apt-get install -y python3-venv iproute2
```

The example uses a dummy interface in a separate network namespace, an explicit
IPv4 target and a test-only systemd namespace override. It does not alter the
VM's default route or claim WAN reachability. The shipped service normally
observes its host namespace; do not set PrivateNetwork and assume it still sees
the host. Runtime uses the installed wheel as the dedicated pathquill account.

No Pathquill installation/account/unit may already exist. The installer refuses
existing paths. Use a separate VM if you have an installation you want to keep.
This is an existing-VM/fresh-application-path test, not a new clean-OS qualification.

## One-command reproducible demonstration

From the checkout inside the VM:

```sh
sudo timeout 600 python3 tools/deployment.py orchestrate-use-case
```

The orchestrator builds the MIT wheel from fingerprinted source, includes LICENSE,
checks wheel and installed module bytes, installs using deploy/install.sh, and
runs the actual systemd service and subprocess CLI. Source tests execute
separately against those same module bytes. No recorder is substituted, no
incident is pre-seeded, and no production method is patched.

It runs both the first real TCP incident and a new real incident after manual
store handoff. Completion is determined by CLI state, verified package content
and process exit, not a fixed sleep pretending that work completed. The normal
capture takes at least 30 seconds; the whole flow takes longer. A nonzero exit,
outer timeout, missing case or cleanup failure means failure.

Outputs:

| Output | Treatment |
| --- | --- |
| evidence/use-case.json and .html | Public verification report; same result object |
| results/use-case/runs/RUN_ID/public-package/ | Exact copied product files, checked before being labelled shareable |
| results/use-case/runs/RUN_ID/private-cli.jsonl | **Private** raw CLI replies/errors, directory 0700 and file 0600; never commit |
| examples/tcp-recovery/package/ | Checked-in copy from the recorded successful run, not rewritten by rerunning the demo |

The report names its output directory and records per-file hashes/lengths so you
can bind the checked-in sample to an actual export. Each run gets a new local
output directory. Reports from failed attempts are retained separately under
evidence/use-case-attempts. The runner removes only its fresh application paths,
account, unit and namespace after stopping the service and verifying the cgroup
is empty. Prerequisite OS packages and local results remain. It does not stop the
VM; stop only your own disposable VM after reviewing the results.

## Hands-on operation sequence

The following is a Bash walkthrough of the same operation contract. The automated
runner uses generated namespace names and private IDs; values below are a declared
synthetic topology. Terminal choreography has not been separately tested by an
external user. The CLI operations themselves are exercised by the runner.

### 1. Install and declare the topology

In terminal A, from a fresh checkout/install location:

```bash
set -euo pipefail
pq_checkout="$PWD"
pq_private=$(mktemp -d)
python3 -m venv "$pq_private/builder"
"$pq_private/builder/bin/python" -m pip wheel --no-deps --wheel-dir "$pq_private/wheels" "$pq_checkout"
sudo sh deploy/install.sh "$pq_private/wheels/pathquill-0.0.1-py3-none-any.whl"
pq_ns=pq-example
sudo ip netns add "$pq_ns"  # refuses a pre-existing name
sudo ip -n "$pq_ns" link set lo up
sudo ip -n "$pq_ns" link add pqprivate0 type dummy
sudo ip -n "$pq_ns" link set pqprivate0 address 02:11:22:33:44:55
sudo ip -n "$pq_ns" address add 198.18.0.1/24 dev pqprivate0
sudo ip -n "$pq_ns" link set pqprivate0 up
sudo ip -n "$pq_ns" route add 198.19.0.0/24 dev pqprivate0
sudo mkdir -p /etc/systemd/system/pathquill.service.d
printf '[Service]\nNetworkNamespacePath=/run/netns/%s\n' "$pq_ns" | sudo tee /etc/systemd/system/pathquill.service.d/namespace.conf >/dev/null
printf '%s\n' '[{"host":"198.18.0.1","port":29871,"timeout":0.2,"interval":0.5}]' | sudo tee /etc/pathquill/config.json >/dev/null
sudo systemctl daemon-reload
```

These addresses and MAC are synthetic test inputs. They must not appear in the
shareable product files, including their hex representations. They are not secret
credentials. The namespace contains the entire target; no external server is used.

### 2. Start the TCP target and observe healthy state

In terminal B, start this listener in the foreground and keep the terminal open:

```sh
sudo ip netns exec pq-example /opt/pathquill/venv/bin/python -I -c '
import socket
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(("198.18.0.1",29871)); s.listen(128)
while True:
    c,a=s.accept(); c.close()
'
```

Back in terminal A:

```bash
pq_root=/var/lib/pathquill/store
pq() { sudo -u pathquill /opt/pathquill/venv/bin/python -I -m pathquill.cli --root "$pq_root" "$@"; }
sudo systemctl start pathquill.service
pq --op status > "$pq_private/status.json"
```

Type=simple means systemctl active is not application readiness. Retry status
if the control socket does not yet exist. Proceed only when state is RECORDING
and health["0"] is success. Keep the raw response private. Save authority:

```bash
pq_store=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["store_id"])' < "$pq_private/status.json")
pq_epoch=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["epoch"])' < "$pq_private/status.json")
```

### 3. Cause failure and then recover

Stop terminal B's listener with Ctrl-C. Refresh status in terminal A until health
is refused and an incident is CAPTURING; then save its ID:

```bash
pq --op status > "$pq_private/status.json"
pq_incident=$(python3 -c 'import json,sys; print(next(x["id"] for x in json.load(sys.stdin)["incidents"] if x["state"]=="CAPTURING"))' < "$pq_private/status.json")
```

Restart the same listener command in terminal B. Refresh status until health is
success and that incident becomes SEALED with recovered=true. Sealing requires
committed progress after the capture window; a successful connection alone is
not proof that the incident is sealed. The prebuffer can be shorter than 60
seconds after startup; recovered does not imply complete observation coverage.

### 4. Export, copy and verify before retirement

```bash
pq --op export --request incident_demo --id "$pq_incident" --seconds 60 --store "$pq_store" --epoch "$pq_epoch" > "$pq_private/request.json"
pq --op export-status --request incident_demo > "$pq_private/export-status.json"
```

Poll export-status until SNAPSHOT_READY. FAILED, EXPIRED, INTERRUPTED or BLOCKED
is not success. The 60-second request deadline is finite; do not reuse a terminal
request ID expecting it to start new work.

```bash
pq --op export-read --request incident_demo > "$pq_private/snapshot-reply.json"
pq --op export-publish --request incident_demo --store "$pq_store" --epoch "$pq_epoch" > "$pq_private/published.json"
pq_package=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["export"]["package"])' < "$pq_private/published.json")
sudo cp -a "/var/lib/pathquill/store/packages/$pq_package" "$pq_private/copied-package"
sudo chown -R "$(id -u):$(id -g)" "$pq_private/copied-package"
```

Run this check from the checkout before sharing or retiring the managed package:

```bash
python3 - "$pq_private/copied-package" "$pq_store" "$pq_epoch" "$pq_incident" "$pq_package" <<'PYCHECK'
import pathlib,sys
from tools.use_case_checks import verify_package
p=pathlib.Path(sys.argv[1])
sensitive=set(sys.argv[2:]) | {'198.18.0.1','c6120001','127.0.0.1','7f000001',
    '::1','00000000000000000000000000000001','pqprivate0',
    '02:11:22:33:44:55','021122334455','/var/lib/pathquill/store'}
print(verify_package({f.name:f.read_bytes() for f in p.iterdir()},sensitive))
PYCHECK
```

The product package contains snapshot.json, index.html and manifest.json. Verify
manifest hashes and lengths before sharing; the automated demo additionally
checks actual failure followed by success, all three state groups, and endpoint
alias relationships. It checks known raw IP/MAC/interface values, packed hex,
store/epoch/incident/package IDs and the raw store path against every file.
The acceptance checker has negative tests: a valid manifest cannot hide an
injected sensitive value or missing failure/recovery evidence.

Download/open index.html locally to read the escaped JSON; GitHub's file view
shows HTML source rather than hosting an interactive application. The package
shows **what this probe observed**, not a root-cause diagnosis. Aliases preserve
relationships within this snapshot, not original names. Hashes detect byte
changes; they do not authenticate who produced the package.

### 5. Retire the product files, keep history

After verifying a retained copy:

```bash
pq --op publication-retire --request incident_demo --package "$pq_package" --store "$pq_store" --epoch "$pq_epoch" > "$pq_private/retirement.json"
pq --op publication-status --request incident_demo > "$pq_private/retirement-status.json"
```

Wait for CLEANED. Only then must the managed package be absent and its reserved
file/snapshot bytes released. The independently copied package remains. This is
not secure erasure, tracking of external readers, or deletion of copied files.
The request-history slot remains occupied.

### 6. Reach 32 slots and observe safe refusal

Keep the raw sealed incident until these admissions are complete:

```bash
for pq_i in {1..31}; do
  pq --op export --request "history_$pq_i" --id "$pq_incident" --seconds 60 --store "$pq_store" --epoch "$pq_epoch" >/dev/null
  pq --op export-cancel --request "history_$pq_i" --store "$pq_store" --epoch "$pq_epoch" >/dev/null
done
if pq --op export --request overflow --id "$pq_incident" --seconds 60 --store "$pq_store" --epoch "$pq_epoch" > "$pq_private/overflow.json"; then
  echo 'Unexpected admission: stop and inspect' >&2; exit 1
fi
pq --op delete --id "$pq_incident" --store "$pq_store" --epoch "$pq_epoch" > "$pq_private/raw-deletion.json"
pq --op status > "$pq_private/full-status.json"
```

Require export_history_full, used=32/remaining=0, no raw incident and no holds.
Deletion is explicit operator permission to remove raw capture data, even before
retention expires. It does not free history slots. Repeating incident_demo with
its original parameters returns RETIRED rather than replaying it.

### 7. Seal, archive in place, start a distinct store

Stop the service **before** stopping the target listener, then remove probe
targets to provide an idle sealing interval. This planned restart is part of
manual handoff, not failure recovery or an uninterrupted-service promise:

```bash
sudo systemctl stop pathquill.service
# Stop terminal B's listener now.
printf '[]\n' | sudo tee /etc/pathquill/config.json >/dev/null
sudo systemctl start pathquill.service
pq --op status > "$pq_private/idle-status.json"
# Wait for RECORDING; retain the stable store ID and refresh the runtime epoch.
pq_epoch=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["epoch"])' < "$pq_private/idle-status.json")
pq --op store-seal --store "$pq_store" --epoch "$pq_epoch" > "$pq_private/seal.json"
# Wait for MainPID=0 before these offline commands:
pq --op store-archive --store "$pq_store" > "$pq_private/archive-reply.json"
sudo -u pathquill /opt/pathquill/venv/bin/python -I -m pathquill.cli --root /var/lib/pathquill/new-store --op store-new --archive "$pq_root" --store "$pq_store" > "$pq_private/new-store.json"
printf '[Service]\nExecStart=\nExecStart=/opt/pathquill/venv/bin/python -I -m pathquill.daemon --root /var/lib/pathquill/new-store --config /etc/pathquill/config.json\n' | sudo tee /etc/systemd/system/pathquill.service.d/root.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl start pathquill.service
pq_root=/var/lib/pathquill/new-store
pq --op status > "$pq_private/fresh-status.json"
```

Require a different store ID, new epoch and zero history entries. Refresh both
before issuing new operations. Old epoch/store/source values must be rejected.
The automatic demo also restores the target configuration, repeats an actual
failure/recovery in the new store, admits a new export request and cancels it;
new history becomes 1. The old sealed DB remains byte-identical.

The archive is the **private old store plus an in-place integrity receipt**, not
an independent backup. Never upload the store, archive receipt or raw CLI files.
No automatic rollover, migration, truncation or reuse of the old path occurs.

For manual cleanup, first stop the service and listener and confirm no namespace
process remains. Preserve needed copies/private archives. Installation removal is
an operator decision; the installer is not an upgrade/uninstall engine. The
automated demo owns and removes only its own fresh fixture installation.

## Evidence and limits

See [use-case JSON](../evidence/use-case.json) / [HTML](../evidence/use-case.html)
and [the copied product package](../examples/tcp-recovery/README.md).
Existing benchmark reports stay unchanged: the runtime implementation is the same;
this addition changes demonstration tools/tests, not the application's features.
The deployment runner now includes LICENSE when copying build inputs.

This checks known synthetic raw values and positive evidence preservation. It
does not prove universal anonymity or cover arbitrary future fields. It is one
local IPv4 refusal/recovery scenario, not WAN diagnosis, sustained overload,
long-term resource stability, installed-service VM reboot/autostart, sudden
power loss or zero-gap boot qualification. No external-user usability study has
yet been performed.

## Recorded successful run (2026-10-30)

The use-case worker completed in about 73 seconds on the existing isolated
Linux VM. All three required cases and orchestrator cleanup passed. The source
suite passed 115 tests (the earlier closeout suite had 111; four added checks
challenge disclosure/evidence validation and invalid demo invocation). All 14
installed runtime modules match the unmodified production source. This is elapsed
workflow time, not a latency SLA or a benchmark comparison.

The copied package has 362 observations and retains TCP refusal/success evidence
and address/interface aliases. All three product files passed checks against
16 known sensitive fixture values, and copies retain the recorded exact hashes.
The first attempt failed because the demonstration queried the socket before
application readiness. Its failed report remains in evidence/use-case-attempts;
the helper now retries only missing/refused startup sockets within a bounded
wait. No product change or relaxed acceptance criterion was used.

The benchmark records and their old tool/test hashes are historical. New runner
mode and tests have their own fingerprints in use-case.json. No prior 330-second
resource result is being represented as a new measurement.

## Observed checkpoints

These are observations from the recorded VM run, not fixed wait times.

| Checkpoint | Seconds from worker start |
| --- | --- |
| healthy_installed_service | 2.51 |
| tcp_refused_capture | 3.67 |
| tcp_success_after_recovery | 5.24 |
| sealed_recovered | 34.68 |
| published_and_copy_verified | 35.85 |
| retired_and_raw_reclaimed | 41.07 |
| manual_seal_archive_new_store | 41.69 |
| new_store_accepts_fresh_real_work | 72.67 |
