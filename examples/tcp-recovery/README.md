# Recorded TCP recovery example

The three files in [package/](package/) are byte-for-byte copies of the actual
product package from the successful use-case VM run. They were not fabricated or
rewritten for presentation. [Verification JSON](../../evidence/use-case.json) and
[HTML](../../evidence/use-case.html) contain their hashes and lengths.

- [snapshot.json](package/snapshot.json): fixed incident and allowlisted observations.
- [index.html](package/index.html): the same JSON escaped into HTML; download/open
  locally (GitHub displays source).
- [manifest.json](package/manifest.json): exact lengths and SHA256 hashes of the
  snapshot and HTML, not a signature or source-authentication proof.

This snapshot contains 362 observations, including 3 TCP refusals and 58
successes, plus link/address/route context. A failure near the incident trigger
is followed by a later success. Recovered=true means fresh successful probes
were observed before sealing; coverage remains a separate property. This
short-startup capture does not promise a full 60-second prebuffer or identify
why a remote system would fail.

Known fixture IP/MAC/interface names, packed address hex, private administrative
IDs and the original store path were checked against every product file (16
values for this run). Actual alias relationships and failure/recovery evidence
were also required, so merely deleting all useful data cannot pass. These checks
are a fixture-specific disclosure test, not universal anonymity certification.

The raw CLI trace, store and archive receipt were not copied here. The retained
package is an independent copy: managed package retirement and explicit raw
incident deletion do not revoke this copy or release request-history slots.
See [the complete walkthrough](../../docs/USE_CASE.md) to reproduce the flow.
