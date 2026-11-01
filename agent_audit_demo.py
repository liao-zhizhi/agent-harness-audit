#!/usr/bin/env python3
"""
agent_audit_demo.py - a minimal demonstration of execution-layer false completion.

Requires
--------
Python 3.8 or newer. Standard library only: no pip install, no virtualenv.
A POSIX shell with `bash` must be on PATH (the demo shells out to `bash -c`).
Native Windows has no `bash`; use WSL, Git Bash, or any Linux/macOS environment.

Verified on: CPython 3.8.20, 3.9.25, 3.12.3, 3.13.18 (all four exit 0).

This is the runnable counterpart to the paper's §5.2 (masked failures) and
§6.1, level 3 (mutation probing). It is deliberately small and dependency-free.

THE STORY IT TELLS
------------------
1. A harness runs a tool command. The harness pipes the command's output through
   a formatter (`cat`), which is normal, and reads the pipeline's exit status.
2. The command fails. The pipeline's exit status is the *formatter's* status, so
   it is 0. The harness has observed success.
3. The agent reads 0 and reports "Task Completed Successfully". It is not lying.
   It is reporting a signal that was never able to say anything else.

THE AUDIT
---------
The auditor does not trust the reported status and does not need to re-run the
command (re-running would raise the staleness problem, mode 2). It instruments
ONE execution so that the same run yields both:

    masked_status  - what the harness/agent saw   (the pipeline's status)
    true_status    - what the command actually returned (PIPESTATUS[0])

If masked == 0 and true != 0, the failure was masked. Verdict: INVALID.
That is a positive finding: it demonstrates constructively that the success
signal is a decoration, not that the tool is unreliable in general.

WHY INVALID AND NOT FAIL
------------------------
The agent's task did not necessarily fail - we are not scoring the task. What
failed is the *observability* of the execution: the audit could not establish
that the reported success was evidence. Per the paper's §6.2 alphabet,
"the audit ran but a level could not be evaluated" is INVALID, and INVALID is
neither PASS nor FAIL.

MUTATION PROBING (the part that makes this an audit and not a demo)
-------------------------------------------------------------------
An auditor that always says INVALID is as useless as one that always says PASS.
So the script also runs the auditor against a harness whose transport is fixed
(`set -o pipefail`), and against commands that genuinely succeed. The auditor
must report PASS there. If it does not, the auditor is broken, not the harness.

Run:  python3 agent_audit_demo.py
Exit: 0 if the auditor behaved correctly on every mutant, 1 otherwise.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum


class Verdict(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INVALID = "INVALID"
    NOT_RUN = "NOT RUN"


@dataclass
class Observation:
    """One instrumented execution: what the agent saw, and what really happened."""

    masked_status: int | None
    true_status: int | None
    stdout: str
    command: str


# --------------------------------------------------------------------------
# 1. The harness under audit
# --------------------------------------------------------------------------
def execute_tool(command: str, pipe_formatter: bool = True) -> Observation:
    """Run a shell command the way a typical agent harness does.

    pipe_formatter=True reproduces the defect: the command's output is piped
    through a formatter, so the pipeline's exit status belongs to the formatter,
    not to the command.

    The instrumented wrapper captures BOTH statuses from a single execution.
    Note the two lines that must not be reordered: `${PIPESTATUS[@]}` is expanded
    by printf, and ANY command in between (even `m=$?`) would overwrite it.
    """
    if pipe_formatter:
        body = f"{command} 2>/dev/null | cat"
        wrapper = (
            "set +o pipefail\n"
            f"{body}\n"
            # The agent sees the status of the LAST stage, which is the formatter.
            # Indexing PIPESTATUS[1] would be wrong whenever the command itself
            # contains a pipe, so we read the last element instead.
            "printf '\\n%s|%s' \"${PIPESTATUS[0]}\" \"${PIPESTATUS[-1]}\"\n"
        )
    else:
        body = command
        wrapper = (
            "set -o pipefail\n"
            f"{body} 2>/dev/null\n"
            # Leading newline so a command emitting no trailing newline cannot
            # fuse its output with the status payload.
            "printf '\\n%s|%s' \"$?\" \"$?\"\n"
        )

    proc = subprocess.run(
        ["bash", "-c", wrapper],
        capture_output=True,
        text=True,
        # A command that emits non-UTF-8 bytes would otherwise raise here and
        # kill the audit instead of producing a verdict. Decode with replacement
        # so a mangled tail is reported rather than the auditor dying silently.
        errors="replace",
        timeout=30,
    )
    tail, _, payload = proc.stdout.rpartition("\n")
    try:
        true_s, masked_s = payload.strip().split("|")
        true_status, masked_status = int(true_s), int(masked_s)
    except ValueError:
        return Observation(None, None, proc.stdout, command)
    return Observation(masked_status, true_status, tail, command)


# --------------------------------------------------------------------------
# 2. The agent, which is not lying
# --------------------------------------------------------------------------
def agent_reports(obs: Observation) -> str:
    """A ReAct-style agent reading only the exit status it was given."""
    if obs.masked_status == 0:
        return "Task Completed Successfully"
    return "Task Failed"


# --------------------------------------------------------------------------
# 3. The auditor
# --------------------------------------------------------------------------
def audit_harness(obs: Observation) -> tuple[Verdict, str]:
    """Decide whether the reported success is evidence.

    The rule is the paper's falsifiability condition, applied to one execution:
    for the success report to be a check, the signal must have been able to
    differ from it. Here we can see directly whether it could.
    """
    if obs.masked_status is None:
        return Verdict.INVALID, "could not parse status from the execution"

    reported = agent_reports(obs)
    if obs.masked_status == 0 and obs.true_status != 0:
        return (
            Verdict.INVALID,
            f"masked failure: agent saw exit {obs.masked_status} and reported "
            f'"{reported}", but the command returned {obs.true_status}',
        )
    if obs.masked_status != obs.true_status:
        return (
            Verdict.INVALID,
            f"status disagreement: masked={obs.masked_status} "
            f"true={obs.true_status}",
        )
    return (
        Verdict.PASS,
        f"no masking: agent saw exit {obs.masked_status}, command returned "
        f"{obs.true_status}",
    )


# --------------------------------------------------------------------------
# 4. The mutants
# --------------------------------------------------------------------------
@dataclass
class Mutant:
    name: str
    command: str
    pipe_formatter: bool
    expected: Verdict
    expected_report: str


MUTANTS = [
    Mutant(
        name="M1  masked failure (the defect)",
        command="find /nonexistent_agent_audit_demo -name '*.log'",
        pipe_formatter=True,
        expected=Verdict.INVALID,
        expected_report="Task Completed Successfully",
    ),
    Mutant(
        name="M2  same command, transport fixed",
        command="find /nonexistent_agent_audit_demo -name '*.log'",
        pipe_formatter=False,
        expected=Verdict.PASS,
        expected_report="Task Failed",
    ),
    Mutant(
        name="M3  command genuinely succeeds",
        command="printf 'ok\\n'",
        pipe_formatter=True,
        expected=Verdict.PASS,
        expected_report="Task Completed Successfully",
    ),
    Mutant(
        name="M4  masked, and the *agent* is also wrong about the outcome",
        command="false",
        pipe_formatter=True,
        expected=Verdict.INVALID,
        expected_report="Task Completed Successfully",
    ),
]


def self_check() -> int:
    """The auditor must be able to fail. Prove it, do not assert it.

    A check is admissible only after it has produced a failing verdict on a
    known-bad fixture (paper §7.4). Here the fixtures are the harness with and
    without the defect: if the auditor returned the same verdict for both, it
    would be a decoration.
    """
    print("\n" + "=" * 72)
    print("SELF-CHECK: can this auditor distinguish a masked failure from a")
    print("clean execution? If every verdict below is identical, it cannot,")
    print("and this whole script is a tautological guardrail (mode 4).")
    print("=" * 72)

    broken = audit_harness(execute_tool("false", pipe_formatter=True))[0]
    clean = audit_harness(execute_tool("false", pipe_formatter=False))[0]
    print(f"  masked harness -> {broken.value}")
    print(f"  fixed  harness -> {clean.value}")
    if broken is clean:
        print("  RESULT: the auditor cannot distinguish them. It is broken.")
        return 1
    print("  RESULT: distinguishable. The auditor's predicate is not vacuous.")
    return 0


def run_mutant(m: Mutant) -> bool:
    obs = execute_tool(m.command, m.pipe_formatter)
    verdict, why = audit_harness(obs)
    report = agent_reports(obs)

    print(f"\n{m.name}")
    print(f"  command      : {m.command}")
    print(f"  formatter    : {'pipe through cat' if m.pipe_formatter else 'none'}")
    print(f"  agent saw    : exit {obs.masked_status}")
    print(f"  command said : exit {obs.true_status}")
    print(f'  agent report : "{report}"')
    print(f"  verdict      : {verdict.value}")
    print(f"  because      : {why}")

    ok = True
    if verdict is not m.expected:
        print(f"  !! MUTANT MISMATCH: expected {m.expected.value}")
        ok = False
    if report != m.expected_report:
        print(f"  !! REPORT MISMATCH: expected {m.expected_report!r}")
        ok = False
    return ok


def preflight() -> int:
    """Fail loudly and helpfully on an unsupported environment.

    An external user on native Windows should not meet a FileNotFoundError
    traceback on their first command. Say what is missing, and say what to do.
    """
    if sys.version_info < (3, 8):
        print(
            f"ERROR: Python 3.8+ required, found "
            f"{sys.version_info.major}.{sys.version_info.minor}.",
            file=sys.stderr,
        )
        return 2
    if shutil.which("bash") is None:
        print(
            "ERROR: this demo needs `bash` on PATH (it shells out to `bash -c`\n"
            "       to capture both the masked and the true exit status).\n"
            "       Native Windows has no bash: use WSL, Git Bash, Linux or macOS.",
            file=sys.stderr,
        )
        return 3
    return 0


def main() -> int:
    rc = preflight()
    if rc != 0:
        return rc

    print("=" * 72)
    print("EXECUTION-LAYER FALSE COMPLETION - minimal audit demo")
    print("companion to: draft_final.md (same directory)")
    print("=" * 72)

    results = [run_mutant(m) for m in MUTANTS]

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    passed = sum(results)
    for m, ok in zip(MUTANTS, results):
        print(f"  [{'ok' if ok else 'XX'}] {m.name}")
    print(f"\n  {passed}/{len(MUTANTS)} mutants behaved as required")

    print(
        "\n  Note what the demo does NOT claim. It does not say the task in M1\n"
        "  failed - the audit is not scoring the task. It says the reported\n"
        "  success was not evidence, because no execution of that harness could\n"
        "  have produced a different report. That is the whole distinction the\n"
        "  paper is about, and it is why the verdict is INVALID rather than FAIL."
    )

    rc = self_check()
    return 0 if (rc == 0 and passed == len(MUTANTS)) else 1


if __name__ == "__main__":
    sys.exit(main())
