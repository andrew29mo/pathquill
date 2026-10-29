# Pathquill

Private Linux network incident recorder, through fixed snapshots and atomic package publication/recovery P0-4c.
No project license has been selected. The formal daemon now collects and
reconstructs state, schedules bounded probes and drives incident lifecycle;
capacity and retention are implemented; durable deidentified snapshots and
JSON/HTML package publication, interrupted-publication reconciliation and
conservative staging cleanup are available. Deployment qualification remains
incomplete. See [recovery contract and evidence](docs/PUBLICATION_RECOVERY.md).
See [publication contract and evidence](docs/PUBLICATION.md),
[snapshot contract and evidence](docs/EXPORT_SNAPSHOT.md), and
[capacity contract and evidence](docs/CAPACITY.md).

The original core is imported by tests; no alternate implementation is used.
The Linux runner exercises an isolated network namespace inside a Colima VM,
then drops to UID 501 before opening the route notification socket. Root only
creates the disposable namespace and dummy interface. The namespace disappears
when the runner and helper processes exit.

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

## Current continuation

See [continued explorations and reproduction](docs/CONTINUED.md),
[current JSON](evidence/continued.json), [HTML](evidence/continued.html), and
[normal VM reboot JSON](evidence/reboot.json) / [HTML](evidence/reboot.html).
The initial record above is historical. Current service behavior and evidence
are described in [Milestone 1](docs/MILESTONE1.md). The current core adds a persistent
observation ring, capture copies, read-only dump interval collection, real
TCP/DNS trigger methods and actual tmpfs ENOSPC/readonly-startup checks.

This is not yet a complete qualified MVP. Current evidence
qualifies bounded primitives; mvp_qualified remains false. No project license
has been selected. No power-loss, physical media failure, zero-gap boot or
long-term stability claims are made. See the continuation guide for precise
injected-versus-real test distinctions and remaining MVP acceptance gates.
