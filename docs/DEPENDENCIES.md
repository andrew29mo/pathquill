# Dependency and license inventory

Reviewed 2026-10-29 against the ed78191 source baseline. This inventory does not
select or grant a license for Pathquill. There is currently no project LICENSE
file or license declaration in pyproject.toml.

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

Project license selection remains an explicit later decision. Adding an upstream
reference here does not relicense that component or Pathquill.
