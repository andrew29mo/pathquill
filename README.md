# Pathquill

Private technical exploration of a bounded Linux network incident recorder.
No project license has been selected. This is a minimal production-core candidate,
not a complete daemon or qualified MVP.

The original core is imported by tests; no alternate implementation is used.
The Linux runner exercises an isolated network namespace inside a Colima VM,
then drops to UID 501 before opening the route notification socket. Root only
creates the disposable namespace and dummy interface. The namespace disappears
when the runner and helper processes exit.

## Reproduce

Python 3.12+ on Linux, iproute2, sudo and unshare are required. From this checkout:

```sh
python3 -m unittest discover -s tests -t . -v
sudo unshare --net python3 tools/explore.py --uid "$(id -u)" --output evidence/exploration.json
```

Run only inside a disposable Linux VM. The Linux runner creates a dummy link,
executes the tests, observes a real link notification as an ordinary account,
and kills a child after its incident transaction commits. JSON and HTML contain
the same result data. Nonzero exit means failed exploration. Full process or
external command hangs are not yet guarded by an outer qualification timeout.

[Observed JSON](evidence/exploration.json), [HTML](evidence/exploration.html),
[architecture and acceptance decisions](docs/ARCHITECTURE.md).

## Current continuation

See [continued explorations and reproduction](docs/CONTINUED.md),
[current JSON](evidence/continued.json), [HTML](evidence/continued.html), and
[normal VM reboot JSON](evidence/reboot.json) / [HTML](evidence/reboot.html).
The initial record above is historical. The current core adds a persistent
observation ring, capture copies, read-only dump interval collection, real
TCP/DNS trigger methods and actual tmpfs ENOSPC/readonly-startup checks.

This is still an exploration-stage core, not a complete daemon. Current evidence
qualifies bounded primitives; mvp_qualified remains false. No project license
has been selected. No power-loss, physical media failure, zero-gap boot or
long-term stability claims are made. See the continuation guide for precise
injected-versus-real test distinctions and remaining MVP acceptance gates.
