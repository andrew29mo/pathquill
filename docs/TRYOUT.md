# Pathquill: first-user trial

**Goal:** capture a local TCP failure and recovery, inspect a verified export,
then retire it and move a full store to a new store. Features are frozen for
this trial. This guide is prepared for a person who did not develop Pathquill;
it is not evidence that such a trial has already happened.

## Before you start

- Use a disposable Linux VM with real systemd as PID 1, Python 3.12+, sudo,
  iproute2 and venv/pip. Allow an initial 30–60 minute session; this is a planning
  allowance, not a measured completion time.
- Use a checkout you own, checked out at the full commit from the supplied trial
  link (not the moving `main` branch). Record `git rev-parse HEAD` and confirm it
  matches that commit; keep this revision throughout the trial. Relative links
  in the commit-pinned guide refer to the same revision. Install prerequisites
  from [What you need](USE_CASE.md#what-you-need).
- The VM must have no existing Pathquill installation, account or service.
  The installer refuses existing paths. Do not try this on a production host.
- Open two Bash terminals. Keep the private temporary directory and raw replies
  private. Never submit a store, archive receipt, raw CLI log or VM credentials.

## Run the hands-on trial

Follow the linked sections in order, in the same terminal sessions. They contain
the exact commands and safety checks; do not skip the checks or replace them
with fixed sleeps. The automated demonstration is an optional reproduction aid,
not a replacement for this manual usability trial.

| Step and instructions | Completion check |
| --- | --- |
| 1. [Install and declare the topology](USE_CASE.md#1-install-and-declare-the-topology) | Fresh wheel installed; isolated synthetic namespace created. The VM default route is not changed. |
| 2. [Start the TCP target](USE_CASE.md#2-start-the-tcp-target-and-observe-healthy-state) | Readiness helper succeeds: `RECORDING` and probe `success`. Save store ID and epoch as instructed. `systemctl active` alone is insufficient. |
| 3. [Cause failure, then recover](USE_CASE.md#3-cause-failure-and-then-recover) | Stop terminal B's listener; observe `refused` and `CAPTURING` before restarting it. Then observe `success` and the same incident `SEALED` with `recovered=true`. Allow at least the 30-second capture window. |
| 4. [Export, copy and verify](USE_CASE.md#4-export-copy-and-verify-before-retirement) | Wait for `SNAPSHOT_READY`; publish, copy to a new private destination and run the supplied verifier successfully. Open the copied `index.html` locally. Identify failure followed by recovery and the aliased network context. |
| 5. [Retire the managed files](USE_CASE.md#5-retire-the-product-files-keep-history) | Wait for `CLEANED`; managed files are removed, your verified copy remains, and the history slot stays used. |
| 6. [Fill the history](USE_CASE.md#6-reach-32-slots-and-observe-safe-refusal) | Require the exact `export_history_full` response, used=32, remaining=0 and no holds before the instructed raw deletion. A timeout or arbitrary error is not proof of capacity refusal. |
| 7. [Seal and start a distinct store](USE_CASE.md#7-seal-archive-in-place-start-a-distinct-store) | Require service exit before offline commands. Old store remains sealed; new store reaches `RECORDING` with a different ID, a new epoch and zero history. Refresh authority before new operations. |

**Stop and record the step** if a command fails unexpectedly, readiness fails,
the incident does not seal, export becomes `FAILED`, `EXPIRED`, `INTERRUPTED` or
`BLOCKED`, verification fails, or store identity is unexpected. Do not delete
unfamiliar files, reuse a terminal request ID to force a retry, or bypass a
refusal. Record elapsed time and the error category without copying raw replies
into feedback. Ask for help if progress stops; help required is useful feedback.

At the end, follow the manual cleanup paragraph in step 7. Stop the service and
listener, confirm namespace processes have exited, and preserve anything you
still need before removing resources or discarding your own VM. Manual cleanup
is not automated uninstall. Product retirement does not erase external copies.

## Limits to understand

- This trial is one synthetic local IPv4 TCP refusal/recovery scenario. It does
  not demonstrate WAN diagnosis or identify a root cause.
- History has **32 permanent request slots per store**. Cancel, delete and
  retirement do not return slots. Handoff is manual; there is no automatic
  rollover. The in-place archive receipt is not an independent backup.
- Exports have a 4,096-row/1 MiB input budget and a 256 KiB snapshot budget;
  high event rates can fail export safely. Observation gaps and a shortened
  startup prebuffer may exist; recovered does not mean complete coverage.
- Aliases preserve relationships. Known-value checks reduce disclosure risk;
  they do not prove anonymity. Review every intended shared file. Hashes detect
  byte changes, not who created a package.
- Long-term stability, current installed-service VM reboot/autostart, sudden
  power-loss recovery and zero-gap boot protection remain unqualified. Earlier
  reboot explorations are not proof for this installed-service workflow.

## Feedback checklist — fill in locally

Keep answers free of real IPs, MACs, interface names, paths, identifiers, tokens
and raw logs. Use a step number and error category instead. Nothing is sent
automatically; review and approve any later sharing separately.

- Commit tested / Linux distribution and version / Python version:
- Result for each step 1–7: **passed / failed / not attempted**:
- Approximate hands-on time and waiting time:
- Did you need help? Which step and what explanation was missing?
- Could you distinguish failure, recovery and sealing in the output?
- Could you explain what the export shows and what it cannot establish?
- Did verification pass before retirement? Could you still read your copy afterward?
- Was the 32-slot refusal understandable? Could you complete handoff and verify
  the new identity and empty history without assistance?
- Was cleanup clear? Any process or resource you could not account for?
- What, if anything, did this evidence help you understand about the failure?
- One confusing instruction and the single most valuable improvement:
- Would you use this for a real incident? In what setting, or why not?

Do not mark unattempted steps as passed. A completed automated run and an
independently completed manual trial should be reported separately.
