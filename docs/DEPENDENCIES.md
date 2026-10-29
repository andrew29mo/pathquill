# Dependency and license inventory

Reviewed 2026-10-29 against the ed78191 source baseline. Pathquill now uses the [MIT License](../LICENSE), selected by its owner on
2026-10-29. pyproject.toml declares SPDX MIT and includes LICENSE in distributions.
Upstream components retain their own terms.

## Source distribution scope

- pyproject.toml declares no third-party Python runtime dependencies.
- Absolute imports in pathquill/ are Python standard-library modules; internal
  modules use package-relative imports. Tests and runners add only standard
  library modules and local pathquill/tools imports.
- The repository contains source, tests, deployment assets, documentation and
  synthetic-fixture verification reports. No vendored runtime, wheel, VM image,
  model, third-party dataset or binary dependency was found in reachable history.
- Deployment creates a venv on the target host. That environment is not committed
  or included in the Pathquill source wheel. This is not a complete host SBOM or
  a vulnerability scan of the OS/build environment.

| Component | Role and distribution | Upstream terms/reference |
| --- | --- | --- |
| Python 3.12+ / standard library | Host runtime; not vendored in repository or source wheel | [PSF License Version 2 and incorporated-software notices](https://docs.python.org/3.12/license.html) |
| SQLite | Used through Python sqlite3 and its host library; no SQLite source/binary included here | [SQLite public-domain dedication](https://www.sqlite.org/copyright.html); retain the target distribution's own packaging notices |
| setuptools >=77 | pyproject build backend; recorded wheel generator is setuptools 84.2.1, not an application runtime dependency | [84.2.1 MIT permission text](https://raw.githubusercontent.com/pypa/setuptools/v84.2.1/LICENSE) |
| pip / venv tooling | External build/install tools supplied on the target host; not part of the Pathquill wheel | Use the installed tools' own distribution notices; this repository does not redistribute them |
| Linux, systemd, iproute2, sudo, POSIX shell | Host/validation prerequisites invoked through OS interfaces; not bundled here | Their host distribution licenses and notices remain separate |
| Colima / virtualization image | External local validation environment, not a shipped Pathquill dependency | No VM/tool binaries or images are committed |

Build isolation can download build tools, so the minimum backend constraint is
not an exact reproducible-build lock. Wheel hashes and module fingerprints record
the measured artifacts; no dependency-free host or reproducible-build guarantee
is made. A future binary/container/VM distribution would need its own complete
component/notice inventory rather than reusing this source-only inventory.

The project MIT license does not relicense upstream components.

## Licensing addendum (2026-10-29)

Only LICENSE, project licensing metadata and documentation changed after the
reviewed code baseline. Existing reports remain immutable measurement records:
their pre-license status strings, old pyproject SHA and old wheel hashes describe
the originally measured artifacts. Runtime and test source fingerprints are
unchanged. The new package is checked separately for MIT metadata, included
license text and byte-identical runtime modules; prior timing/RSS results are
not represented as a fresh measurement of the newly built wheel.

Package verification passed in the isolated Linux VM: the wheel declares
License-Expression: MIT and License-File: LICENSE; wheel and sdist both contain
the exact repository LICENSE. All 14 packaged runtime modules are byte-identical
to the source, with no Requires-Dist runtime dependency. The checked wheel SHA256
is 2d570c2e64a2ef425fe6465d814283b8ddbf9122ed3f6b120d6aceb8e21b8c28.
