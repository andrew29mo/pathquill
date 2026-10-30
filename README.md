# Pathquill

A bounded Linux network incident recorder with fixed snapshots, package publication,
recovery after process crashes and explicit retirement.
Licensed under the [MIT License](LICENSE). The formal daemon now collects and
reconstructs state, schedules bounded probes and drives incident lifecycle;
capacity and retention are implemented; durable deidentified snapshots and
JSON/HTML package publication, interrupted-publication reconciliation and
conservative cleanup, explicit retirement and full-history archive/new-store
workflow are available. See [retention contract and evidence](docs/RETENTION.md).
Installed-package/systemd lifecycle validation is available in
[deployment contract and evidence](docs/DEPLOYMENT.md). The final document-driven
Linux workflow and fixed resource acceptance are described in
[bounded closeout](docs/CLOSEOUT.md). See [recovery contract and evidence](docs/PUBLICATION_RECOVERY.md).
See [publication contract and evidence](docs/PUBLICATION.md),
[snapshot contract and evidence](docs/EXPORT_SNAPSHOT.md), and
[capacity contract and evidence](docs/CAPACITY.md).

Tests import the production core. Earlier namespace runners drop to UID 501;
formal deployment and closeout instead install the wheel and run the real systemd
service as a dedicated unprivileged account. They explicitly distinguish the
default VM network from a test-only namespace override. No alternate recorder
implementation is used. Root prepares isolated fixtures and installs the service;
cleanup checks processes and owned resources before reporting success.

## Complete worked example

Start with [A TCP failure, a shareable package, and a full store](docs/USE_CASE.md).
It includes English setup/operation instructions, a one-command installed-service
VM demonstration, the [actual copied product package](examples/tcp-recovery/README.md)
and [JSON](evidence/use-case.json) / [HTML](evidence/use-case.html) verification.
The flow covers failure/recovery, copy-before-retirement, raw capture reclamation,
32-slot refusal, manual seal/archive/new-store handoff and new real work.
The new demonstration passed 115 source tests; historical 111-test/330-second
records retain their original scope. Production runtime code is unchanged.

## Reproduce

Python 3.12+ on Linux, iproute2, sudo and unshare are required. From this checkout:

```sh
python3 -m unittest discover -s tests -t . -v
sudo timeout 75 unshare --net python3 tools/milestone1.py
```

Run only inside a disposable Linux VM. The milestone runner creates isolated dummy links, runs tests, starts formal
daemons and observes real network failures and recovery. JSON and HTML contain
the same result data. Nonzero exit or the outer timeout means failure. The
earlier exploration runner and its reports are historical.

[Observed JSON](evidence/exploration.json), [HTML](evidence/exploration.html),
[architecture and acceptance decisions](docs/ARCHITECTURE.md).

## Historical exploration records

See [continued explorations and reproduction](docs/CONTINUED.md),
[historical JSON](evidence/continued.json), [HTML](evidence/continued.html), and
[normal VM reboot JSON](evidence/reboot.json) / [HTML](evidence/reboot.html).
These exploration/reboot reports describe their recorded older sources; their
fingerprints differ from the current runtime. They do not qualify VM reboot of
the installed service. The first daemon stage is described in
[Milestone 1](docs/MILESTONE1.md); current deployment and closure are in
[DEPLOYMENT.md](docs/DEPLOYMENT.md) and [CLOSEOUT.md](docs/CLOSEOUT.md).
The implemented core includes a persistent
observation ring, capture copies, read-only dump interval collection, real
TCP/DNS trigger methods and actual tmpfs ENOSPC/readonly-startup checks.

Individual stage reports retain mvp_qualified=false because they each cover a
bounded slice. The planned functional closure and its aggregate verification
status are summarized in [CLOSEOUT.md](docs/CLOSEOUT.md); no stage establishes production readiness. No power-loss, physical media failure, zero-gap boot or
long-term stability claims are made. See each stage guide for injected-versus-real test distinctions, and CLOSEOUT.md
for the completed functional scope and remaining untested boundaries.

## Installed-service closeout

In a newly provisioned disposable Linux VM with the prerequisites and pre-install
receipt documented in [CLOSEOUT.md](docs/CLOSEOUT.md):

```sh
sudo timeout 650 python3 tools/deployment.py orchestrate-closeout
```

[Closeout JSON](evidence/closeout.json) and [HTML](evidence/closeout.html) retain
all resource samples, fixed acceptance thresholds, actual TCP failure/recovery
evidence and installed-package provenance. Failed attempts are retained separately;
this is a bounded local workload, not a production or long-term stability claim.
Exports have a 4,096-row/1 MiB input limit and a 256 KiB snapshot limit. Idle
progress commits are coalesced at 100ms; high event rates can still exceed budgets
and fail export safely. Export history has 32 permanent slots per store; explicit
seal/archive/new-store handoff is available, automatic rollover is not.

## Release status

The final pre-publication review is recorded in
[PREPUBLIC_REVIEW.md](docs/PREPUBLIC_REVIEW.md). The repository is Public,
and is licensed under [MIT](LICENSE). The source/build/host dependency inventory
is in [DEPENDENCIES.md](docs/DEPENDENCIES.md); upstream components retain their own terms.

The MIT addition changes packaging metadata and documentation only. Existing
measurement reports retain their original pyproject fingerprints and pre-license
status text; production runtime/test bytes are unchanged. See the licensing
addendum in [DEPENDENCIES.md](docs/DEPENDENCIES.md).

Public-repository protections and verification are recorded in
[PUBLIC_RELEASE.md](docs/PUBLIC_RELEASE.md). Security reports can be submitted
privately using the process in [SECURITY.md](SECURITY.md).
