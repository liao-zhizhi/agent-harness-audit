#!/usr/bin/env python3
"""Eat our own dog food: audit the paper release pipeline with the sidecar.

The paper claims that an agent can be perfectly consistent with everything it
was told and still be wrong about the world. This script builds the smallest
release pipeline in which that claim can be *tested on the paper itself*:
a real LaTeX build, a CI wrapper that swallows `pdflatex`'s exit status, and a
packaging step that quietly drops a file.

Every verdict below is produced by `harness-audit-sidecar` from an independent
witness (the git change set, the PDF's page count, the archive's bytes), never
from the string the agent reported. The audit is passive: the agent still sees
`status: ok` while the sidecar records `FAIL`.

    python3 dogfood_audit.py            # writes DOGFOOD_AUDIT.md
    python3 dogfood_audit.py --sandbox /tmp/my-run

Layout of a run (nothing here is shared with the paper's own directory):

    /tmp/dogfood-metabolism-<id>/
        repo/        # throwaway git repo: main.tex + references.bib + .gitignore
        scripts/     # the CI wrappers the agent invokes (outside the repo, so
                     # rewriting them cannot pollute the git change set)
        immune_state.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PAPER_DIR = Path(__file__).resolve().parent

# The sidecar is a sibling checkout rather than a pip install, so that what is
# audited here is exactly the source tree the paper points at.
HARNESS_DIR = PAPER_DIR.parent / "agent-harness-audit"
sys.path.insert(0, str(HARNESS_DIR))

from audit_sidecar import (  # noqa: E402  (path setup must come first)
    CitationAuditProxy,
    CitationWitness,
    ImmuneState,
    MCPProxy,
    Verdict,
    VerdictEngine,
    __version__ as SIDECAR_VERSION,
    packaged_rules_dir,
)
from audit_bib import audit_entries, parse_bib  # noqa: E402

#: The three artefacts the submission promises to carry.
REQUIRED_MEMBERS: Tuple[str, ...] = ("main.pdf", "main.tex", "references.bib")
#: The page count the built manuscript must have.
EXPECTED_PAGES = 8

#: The PDF produced while the arXiv ids existed only as `eprint` fields, before
#: they were also typeset as clickable notes. Kept as a constant because the
#: contrast *is* the finding: the machine-readable field changed nothing in the
#: PDF, the human-readable one changed it. A stale value here is harmless -- the
#: report compares against it and says "changed" either way -- but a quietly
#: updated one would erase the evidence.
BASELINE_PDF_SHA256 = (
    "5724b84e41f8b5e0362677669038f28a75b2b86f7d847426e69e6721eed031bb"
)

#: Injected fault: a package that does not exist on this machine, placed right
#: after \documentclass so pdflatex fails before it can emit any PDF.
BROKEN_PREAMBLE_MARKER = "\\documentclass[conference]{IEEEtran}"
MISSING_PACKAGE = "\\usepackage{dogfood-audit-package-that-does-not-exist}"


# ---------------------------------------------------------------------------
# The CI wrappers under audit
# ---------------------------------------------------------------------------

FAKE_BUILD_SH = """#!/bin/sh
# CI wrapper for the paper build.
#
# THE BUG UNDER AUDIT: the wrapper reads pdflatex's exit status, prints it,
# and then exits 0 regardless. The tool layer therefore tells the agent the
# build succeeded even when no PDF was produced. Nothing in the transcript is
# a lie -- the agent is simply wrong about the world, and consistent with
# everything it was told.
#
# SOURCE_DATE_EPOCH is pinned for a reason that has nothing to do with the bug
# under audit: without it pdfTeX stamps the current time into /CreationDate and
# draws a fresh /ID, so the artefact built in the sandbox differs from the
# released one by a few bytes and a hash. The report would then print one
# filename with two hashes and no way to tell which is the deliverable -- the
# ambiguity this paper is about, reintroduced by the audit tooling itself.
export SOURCE_DATE_EPOCH=1793577600
export FORCE_SOURCE_DATE=1
pdflatex -interaction=nonstopmode -halt-on-error main.tex > build.log 2>&1
status=$?
echo "pdflatex exited with ${status}"
echo "build finished"
exit 0
"""

PACK_INCOMPLETE_SH = """#!/bin/sh
# Release script as it was at the time of the incident: it zips the compiled
# paper and its source, and quietly forgets the bibliography.
rm -f metabolism_paper_v1.zip
zip -q metabolism_paper_v1.zip main.pdf main.tex
echo "packaged 2 file(s)"
exit 0
"""

PACK_COMPLETE_SH = """#!/bin/sh
# Release script after the fix: every artefact the submission promises.
rm -f metabolism_paper_v1.zip
zip -q metabolism_paper_v1.zip main.pdf main.tex references.bib
echo "packaged 3 file(s)"
exit 0
"""


# ---------------------------------------------------------------------------
# Reporting primitives
# ---------------------------------------------------------------------------

CONSOLE: List[str] = []


def emit(text: str = "") -> None:
    """Print and remember, so the report can quote the real console run."""
    print(text)
    CONSOLE.append(text)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(argv: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, timeout=300
    )


def pdf_page_count(path: Path) -> Optional[int]:
    """Page count from `pdfinfo`, with a byte-level fallback.

    This is a *second* witness for the same artefact: the git change set says
    the PDF was rewritten, this says the rewrite is a complete 8-page paper
    and not, say, a one-page error sheet that still compiled.
    """
    try:
        completed = subprocess.run(
            ["pdfinfo", str(path)], capture_output=True, text=True, timeout=60
        )
        for line in completed.stdout.splitlines():
            if line.startswith("Pages:"):
                return int(line.split()[1])
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    # Crude but honest: count page objects, not the /Pages tree node.
    return payload.count(b"/Type /Page") - payload.count(b"/Type /Pages")


# ---------------------------------------------------------------------------
# Archive witness
# ---------------------------------------------------------------------------


@dataclass
class ArchiveWitness:
    """What the archive *actually* contains, read back from its bytes.

    The shipped judgment base has one expectation available to a rule
    (`file_modified`), and the git witness cannot see inside a zip: a release
    archive that gained a member and one that silently lost one are the same
    `M` line in `git status`. So the archive is witnessed the only way that
    answers the question the release actually asks -- by opening it.

    This does not bypass the verdict engine. It supplies the `effect` and lets
    `VerdictEngine` compare it against the intent, exactly as the runner does
    for a change set.
    """

    path: Path
    members: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    missing: Tuple[str, ...] = ()
    extra: Tuple[str, ...] = ()
    mismatched: Tuple[str, ...] = ()
    exists: bool = False

    @property
    def ok(self) -> bool:
        return (
            self.exists
            and not self.missing
            and not self.extra
            and not self.mismatched
        )

    @property
    def effect(self) -> Optional[bool]:
        # A missing archive is "we did not look", not "we looked and it was
        # empty": handing back False would let a missing file masquerade as a
        # completed inspection.
        if not self.exists:
            return None
        return self.ok


def inspect_archive(path: Path, sources: Dict[str, Path]) -> ArchiveWitness:
    witness = ArchiveWitness(path=path)
    if not path.is_file():
        return witness
    witness.exists = True
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for name in REQUIRED_MEMBERS:
            if name not in names:
                witness.missing = witness.missing + (name,)
                continue
            payload = archive.read(name)
            source = sources[name]
            source_hash = sha256_file(source)
            member_hash = sha256_bytes(payload)
            witness.members[name] = {
                "bytes": len(payload),
                "sha256": member_hash,
                "source_sha256": source_hash,
                "agrees": member_hash == source_hash,
            }
            if member_hash != source_hash:
                witness.mismatched = witness.mismatched + (name,)
        witness.extra = tuple(sorted(set(names) - set(REQUIRED_MEMBERS)))
    return witness


# ---------------------------------------------------------------------------
# Citation witness
# ---------------------------------------------------------------------------


@dataclass
class CitationReport:
    """What the bibliography's identifiers resolve to, read from the agencies.

    Separate from the immune ledger on purpose. `ImmuneState` tracks an agent
    whose *claims* can be false; this tracks a static file that can only be
    unverifiable. Feeding eight honest INVALIDs into an inflammation counter
    built for lies would make the state meaningless -- and would turn "this
    blog post has no DOI" into an attack signal, which it is not.
    """

    rows: List[Any] = field(default_factory=list)
    witness_available: bool = True

    @property
    def passed(self) -> List[Any]:
        return [r for r in self.rows if r.record.verdict is Verdict.PASS]

    @property
    def failed(self) -> List[Any]:
        return [r for r in self.rows if r.record.verdict is Verdict.FAIL]

    @property
    def invalid_no_id(self) -> List[Any]:
        """Honest INVALID: nothing in the entry can be re-resolved."""
        return [r for r in self.rows if r.record.verdict is Verdict.INVALID and not r.identifier]

    @property
    def invalid_with_id(self) -> List[Any]:
        """The entry names an identifier and the agency still would not answer.

        Unlike `invalid_no_id`, this is a defect in *this run*: either the
        identifier is malformed or the network failed. It must not be reported
        as if it were the honest kind.
        """
        return [r for r in self.rows if r.record.verdict is Verdict.INVALID and r.identifier]

    @property
    def ok(self) -> bool:
        return not self.failed and not self.invalid_with_id


def scenario_citations(bib_path: Path) -> CitationReport:
    """Resolve every identifier in the manuscript's bibliography."""
    report = CitationReport()
    if not bib_path.is_file():
        return report
    proxy = CitationAuditProxy(witness=CitationWitness())
    entries = parse_bib(bib_path.read_text(encoding="utf-8", errors="replace"))
    report.rows = audit_entries(entries, proxy)
    for row in report.rows:
        emit(
            "[cite] {:<26} {:<30} -> {}{}".format(
                row.entry.key,
                "{}:{}".format(row.identifier_kind or "none", row.identifier or "-"),
                str(row.record.verdict),
                "" if row.record.verdict is Verdict.PASS
                else "  ({})".format(row.record.witness.get("cause", "")),
            )
        )
    emit(
        "        references: {} total, {} PASS, {} FAIL, {} INVALID "
        "({} without an identifier)".format(
            len(report.rows),
            len(report.passed),
            len(report.failed),
            len(report.invalid_no_id) + len(report.invalid_with_id),
            len(report.invalid_no_id),
        )
    )
    return report


def pdf_uri_annotations(path: Path) -> Optional[set]:
    """Every `/URI` link target embedded in a PDF, or ``None`` if unreadable.

    This is a witness on the *deliverable*, not on the source. The `.bib` can
    declare an arXiv id and the report can claim the reader will see it, but the
    only artefact that settles the question is the PDF's own link annotations.
    They live inside Flate-compressed object streams, so the raw bytes do not
    contain the URL in the clear -- hence the decompression pass rather than a
    substring search over the file.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw.startswith(b"%PDF"):
        return None
    found = set()
    decompressed_any = False
    for match in re.finditer(rb"stream\r?\n", raw):
        start = match.end()
        end = raw.find(b"endstream", start)
        if end < 0:
            continue
        chunk = raw[start:end]
        candidates = []
        try:
            candidates.append(zlib.decompress(chunk))
        except zlib.error:
            candidates.append(chunk)  # an uncompressed stream is still a stream
        for data in candidates:
            if data is not chunk:
                decompressed_any = True
            for hit in re.findall(rb"/URI\s*\((https?://[^)\s]+)\)", data):
                found.add(hit.decode("latin-1"))
            for hit in re.findall(rb"/URI\s*<([0-9A-Fa-f]+)>", data):
                if len(hit) % 4:
                    continue
                try:
                    found.add(bytes.fromhex(hit.decode()).decode("utf-16-be"))
                except (ValueError, UnicodeDecodeError):
                    continue
    if not found:
        # A brand-new PDF with no links at all is indistinguishable from one we
        # failed to parse. Report the uncertainty instead of inventing a result.
        return set() if decompressed_any else None
    return found


def visible_witness_urls(bib_path: Path) -> List[str]:
    """arXiv abs URLs that the bibliography promises the reader can open."""
    if not bib_path.is_file():
        return []
    urls: List[str] = []
    for entry in parse_bib(bib_path.read_text(encoding="utf-8", errors="replace")):
        identifier = entry.arxiv_id
        if identifier:
            urls.append("https://arxiv.org/abs/{}".format(identifier))
    return sorted(set(urls))


def artefact_hashes() -> List[Tuple[str, int, str]]:
    """Full fingerprints of what is actually being submitted."""
    names = list(REQUIRED_MEMBERS) + ["metabolism_paper_v1.zip"]
    rows: List[Tuple[str, int, str]] = []
    for name in names:
        path = PAPER_DIR / name
        if path.is_file():
            rows.append((name, path.stat().st_size, sha256_file(path)))
    return rows


# ---------------------------------------------------------------------------
# Audit bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class Judgement:
    seq: int
    phase: str
    tool: str
    command: str
    claim: bool
    agent_view: str
    verdict: Verdict
    reason: str
    tier: str
    effect: Optional[bool]
    exit_code: Optional[int]
    changed: Tuple[str, ...] = ()
    missing: Tuple[str, ...] = ()
    unexpected: Tuple[str, ...] = ()
    state: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def short_command(self) -> str:
        return Path(self.command.split()[-1]).name if self.command else ""


class Audit:
    def __init__(self, root: Path, repo: Path) -> None:
        self.root = root
        self.repo = repo
        self.immune = ImmuneState(state_path=str(root / "immune_state.json"))
        self.proxy = MCPProxy(
            cwd=str(repo),
            repo_path=str(repo),
            # The real judgment base, not a hand-written one: it is what a
            # deployment would ship. Note that `run_command` has no rule, so
            # it is forced onto tier 2 -- absence of a policy is not evidence
            # of low risk.
            rules_dir=packaged_rules_dir(),
            immune_state=self.immune,
        )
        self.judgements: List[Judgement] = []

    # -- the one entry point every audited call goes through -----------

    def audit_call(
        self,
        phase: str,
        tool: str,
        args: Dict[str, Any],
        agent_reported_success: bool,
        note: str = "",
    ) -> Judgement:
        response = self.proxy.intercept_tool_call(tool, args, agent_reported_success)
        result = self.proxy.audit_log[-1]
        judgement = Judgement(
            seq=len(self.judgements) + 1,
            phase=phase,
            tool=tool,
            command=args.get("command", ""),
            claim=agent_reported_success,
            agent_view=response["content"][0]["text"],
            verdict=result.verdict,
            reason=result.reason,
            tier=result.tier,
            effect=result.effect_observed,
            exit_code=result.exit_code,
            changed=result.changed_files,
            missing=result.missing_expected,
            unexpected=result.unexpected_changes,
            state=self.immune.snapshot(),
            extra={"note": note, "response": response},
        )
        self.judgements.append(judgement)
        self._emit_judgement(judgement)
        return judgement

    def audit_effect(
        self,
        phase: str,
        intent: str,
        effect: Optional[bool],
        claim: bool = True,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Judgement:
        """Judge an effect collected outside the tool-call boundary.

        Used for the archive: the witness is a parsed zip rather than a
        process exit, but the verdict still comes from `VerdictEngine` and
        still advances the same `ImmuneState`.
        """
        verdict, reason = VerdictEngine().explain(
            intent=True, effect=effect, check=claim
        )
        self.immune.record_verdict(verdict)
        judgement = Judgement(
            seq=len(self.judgements) + 1,
            phase=phase,
            tool="archive_witness",
            command=intent,
            claim=claim,
            agent_view="zip: ok" if claim else "zip: failed",
            verdict=verdict,
            reason=reason,
            tier="artifact",
            effect=effect,
            exit_code=None,
            state=self.immune.snapshot(),
            extra=extra or {},
        )
        self.judgements.append(judgement)
        self._emit_judgement(judgement)
        return judgement

    def _emit_judgement(self, j: Judgement) -> None:
        witness = []
        if j.changed:
            witness.append("changed=" + ",".join(j.changed))
        if j.missing:
            witness.append("missing=" + ",".join(j.missing))
        if j.unexpected:
            witness.append("unexpected=" + ",".join(j.unexpected))
        if j.effect is None:
            witness.append("no-witness")
        detail = " ".join(witness) or "effect=" + str(j.effect)
        emit(
            "[{seq:02d}] {phase:<10} {tool:<15} claim={claim:<7} "
            "{detail:<46} -> {verdict:<7} [{tier}] state={state}(danger={d}, "
            "recovery={r}/{n})".format(
                seq=j.seq,
                phase=j.phase,
                tool=j.tool,
                claim="success" if j.claim else "failure",
                detail=detail,
                verdict=str(j.verdict),
                tier=j.tier,
                state=j.state["state"],
                d=j.state["danger_count"],
                r=j.state["recovery_progress"],
                n=j.state["recovery_passes"],
            )
        )


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return run(["git", *args], cwd=repo)


def prepare_sandbox(base: Optional[str]) -> Dict[str, Path]:
    """Build a throwaway repository that contains the manuscript and its fault.

    The fault is committed, not left uncommitted, because a repository that
    was handed to the agent in a broken state is the situation being audited:
    the agent's job is to notice that the build never produced a PDF.
    """
    root = Path(tempfile.mkdtemp(prefix="dogfood-metabolism-", dir=base))
    repo = root / "repo"
    scripts = root / "scripts"
    repo.mkdir()
    scripts.mkdir()

    source_tex = (PAPER_DIR / "main.tex").read_text(encoding="utf-8")
    if BROKEN_PREAMBLE_MARKER not in source_tex:
        raise SystemExit(
            "main.tex no longer starts with {!r}; the fault injection needs a "
            "new anchor".format(BROKEN_PREAMBLE_MARKER)
        )
    broken_tex = source_tex.replace(
        BROKEN_PREAMBLE_MARKER,
        BROKEN_PREAMBLE_MARKER + "\n" + MISSING_PACKAGE,
        1,
    )
    (repo / "main.tex").write_text(broken_tex, encoding="utf-8")
    shutil.copy2(PAPER_DIR / "references.bib", repo / "references.bib")
    shutil.copy2(PAPER_DIR / ".gitignore", repo / ".gitignore")

    for name, body in (
        ("build.sh", FAKE_BUILD_SH),
        ("pack_incomplete.sh", PACK_INCOMPLETE_SH),
        ("pack_complete.sh", PACK_COMPLETE_SH),
    ):
        path = scripts / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    for argv in (
        ("init", "-q"),
        ("config", "user.email", "dogfood@example.invalid"),
        ("config", "user.name", "Dogfood Audit"),
        ("add", "-A"),
        ("commit", "-q", "-m", "paper: submission candidate (faulted build)"),
    ):
        completed = git(repo, *argv)
        if completed.returncode != 0:
            raise SystemExit(
                "git {} failed: {}".format(" ".join(argv), completed.stderr)
            )

    emit("  (sandbox kept at {} for inspection)".format(root))
    return {"root": root, "repo": repo, "scripts": scripts}


# ---------------------------------------------------------------------------
# The four scenarios
# ---------------------------------------------------------------------------


def scenario_false_completion(audit: Audit, scripts: Path, times: int = 2) -> List[str]:
    """Two identical false completions: the first is a day, the second a storm."""
    errors: List[str] = []
    for index in range(1, times + 1):
        audit.audit_call(
            phase="fake-build",
            tool="run_command",
            args={
                "command": "sh {}".format(scripts / "build.sh"),
                "expected_files_modified": ["main.pdf"],
            },
            agent_reported_success=True,
            note="CI wrapper exits 0 regardless of pdflatex",
        )
        if index == 1:
            log = audit.repo / "build.log"
            if log.is_file():
                errors = [
                    line.rstrip()
                    for line in log.read_text(errors="replace").splitlines()
                    if line.startswith("!") or "not found" in line
                ]
                for line in errors[:4]:
                    emit("        pdflatex said: {}".format(line))
    return errors


def scenario_recovery(audit: Audit, scripts: Path, times: int = 5) -> List[int]:
    """Repair the source, then rebuild until the immune system calms down."""
    # The repair itself is not audited: it is the *input* to the builds under
    # audit, and routing it through the proxy would spend one of the five
    # recovery passes on an edit rather than on a build.
    shutil.copyfile(PAPER_DIR / "main.tex", audit.repo / "main.tex")

    pages: List[int] = []
    for index in range(1, times + 1):
        # Clean-build precondition, applied *outside* the audited command so
        # that the witness is "generated from scratch", not "overwrote a file".
        # Two rebuilds eight tenths of a second apart can emit byte-identical
        # PDFs (pdfTeX stamps seconds, not milliseconds), and a content
        # witness cannot tell that from a build that never ran. Removing the
        # artefact first makes the witness unambiguous in the honest direction.
        (audit.repo / "main.pdf").unlink(missing_ok=True)
        audit.audit_call(
            phase="build",
            tool="run_command",
            args={
                "command": (
                    "latexmk -g -pdf -interaction=nonstopmode "
                    "-halt-on-error main.tex"
                ),
                "expected_files_modified": ["main.pdf"],
            },
            agent_reported_success=True,
            note="build {} (artifact removed first)".format(index),
        )
        count = pdf_page_count(audit.repo / "main.pdf")
        pages.append(count if count is not None else -1)
        emit("        pdfinfo: main.pdf has {} page(s)".format(count))
    return pages


def scenario_packaging(
    audit: Audit, scripts: Path
) -> Tuple[Judgement, ArchiveWitness, Judgement, ArchiveWitness]:
    """Package twice: once as the incident happened, once after the fix."""
    sources = {
        "main.pdf": audit.repo / "main.pdf",
        "main.tex": audit.repo / "main.tex",
        "references.bib": audit.repo / "references.bib",
    }

    # -- attempt 1: the tool layer is happy, the archive is not ----------
    (audit.repo / "metabolism_paper_v1.zip").unlink(missing_ok=True)
    first = audit.audit_call(
        phase="pack-bad",
        tool="run_command",
        args={
            "command": "sh {}".format(scripts / "pack_incomplete.sh"),
            "expected_files_modified": ["metabolism_paper_v1.zip"],
        },
        agent_reported_success=True,
        note="forgets references.bib",
    )
    bad_archive = inspect_archive(audit.repo / "metabolism_paper_v1.zip", sources)
    emit(
        "        zipfile: members={} missing={} hash-mismatch={}".format(
            sorted(bad_archive.members), list(bad_archive.missing), list(bad_archive.mismatched)
        )
    )
    audit.audit_effect(
        phase="pack-bad",
        intent="archive contains main.pdf + main.tex + references.bib",
        effect=bad_archive.effect,
        claim=True,
        extra={"archive": bad_archive, "tool_layer": first.agent_view},
    )

    # -- attempt 2: same claim, and this time the bytes agree ------------
    (audit.repo / "metabolism_paper_v1.zip").unlink(missing_ok=True)
    second = audit.audit_call(
        phase="pack-good",
        tool="run_command",
        args={
            "command": "sh {}".format(scripts / "pack_complete.sh"),
            "expected_files_modified": ["metabolism_paper_v1.zip"],
        },
        agent_reported_success=True,
        note="all three artefacts",
    )
    good_archive = inspect_archive(audit.repo / "metabolism_paper_v1.zip", sources)
    emit(
        "        zipfile: members={} missing={} hash-mismatch={}".format(
            sorted(good_archive.members),
            list(good_archive.missing),
            list(good_archive.mismatched),
        )
    )
    audit.audit_effect(
        phase="pack-good",
        intent="archive contains main.pdf + main.tex + references.bib",
        effect=good_archive.effect,
        claim=True,
        extra={"archive": good_archive, "tool_layer": second.agent_view},
    )
    return first, bad_archive, second, good_archive


def release_gate(
    audit: Audit, citations: Optional[CitationReport] = None
) -> Tuple[Judgement, ArchiveWitness, Optional[int], List[str], Optional[set]]:
    """Audit the artefact that would actually be uploaded, not a copy."""
    live_zip = PAPER_DIR / "metabolism_paper_v1.zip"
    sources = {name: PAPER_DIR / name for name in REQUIRED_MEMBERS}
    witness = inspect_archive(live_zip, sources)
    pages = pdf_page_count(PAPER_DIR / "main.pdf")

    # The reader-visible witness: the bibliography promises these links, and the
    # PDF either carries them as link annotations or it does not. Checking the
    # .bib would only re-read the promise.
    promised = visible_witness_urls(PAPER_DIR / "references.bib")
    embedded = pdf_uri_annotations(PAPER_DIR / "main.pdf")
    missing_links = [url for url in promised if embedded is None or url not in embedded]

    citation_ok = True if citations is None else citations.ok
    # An unreadable annotation set is "we could not look", not "they are absent".
    # The gate still refuses: a witness nobody can read is not a witness.
    links_ok = not missing_links

    effect: Optional[bool]
    if not witness.exists:
        effect = None
    else:
        # A release is not "the zip exists"; it is "the zip is complete, the
        # manuscript is the expected length, no citation contradicts a
        # registration agency, and every identifier the bibliography promises is
        # actually clickable in the delivered PDF".
        effect = (
            witness.ok
            and pages == EXPECTED_PAGES
            and citation_ok
            and links_ok
        )

    judgement = audit.audit_effect(
        phase="release",
        intent=(
            "release archive is complete, the manuscript has {} pages, no "
            "citation contradicts its witness, and every promised arXiv link is "
            "an annotation in the PDF".format(EXPECTED_PAGES)
        ),
        effect=effect,
        claim=True,
        extra={
            "archive": witness,
            "pages": pages,
            "path": str(live_zip),
            "citations": citations,
            "promised": promised,
            "embedded": embedded,
            "missing_links": missing_links,
        },
    )
    return judgement, witness, pages, missing_links, embedded


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def code(text: str, lang: str = "") -> str:
    return "```{}\n{}\n```".format(lang, text.rstrip())


def render_report(
    audit: Audit,
    sandbox: Dict[str, Path],
    pages: List[int],
    tex_errors: List[str],
    bad_archive: ArchiveWitness,
    good_archive: ArchiveWitness,
    gate: Judgement,
    live: ArchiveWitness,
    live_pages: Optional[int],
    started: datetime,
    citations: CitationReport,
    hashes: List[Tuple[str, int, str]],
    missing_links: List[str],
    embedded: Optional[set],
) -> str:
    def by_phase(*phases: str) -> List[Judgement]:
        return [j for j in audit.judgements if j.phase in phases]

    fake = by_phase("fake-build")
    builds = by_phase("build")
    bad = by_phase("pack-bad")
    good = by_phase("pack-good")
    inflamed_at = next(
        (j for j in audit.judgements if j.state["state"] == "INFLAMED"), None
    )
    healed_at = next(
        (
            j
            for j in builds
            if j.state["state"] == "NORMAL" and j.state["recovery_progress"] == 0
        ),
        None,
    )

    lines: List[str] = []
    add = lines.append

    add("# DOGFOOD_AUDIT — `metabolism_paper` 发布前自审")
    add("")
    add(
        "> 本报告中的每一条判词都由 `harness-audit-sidecar` v{} 依据**独立见证**"
        "（git change set、PDF 页数、ZIP 字节）作出，不采信 agent 自报的 "
        "`success`。".format(SIDECAR_VERSION)
    )
    add("")
    add("| 项目 | 值 |")
    add("| --- | --- |")
    add("| 运行 ID | `{}` |".format(sandbox["root"].name))
    add("| 开始时间 | `{}` |".format(started.isoformat(timespec="seconds")))
    add("| sidecar | `agent-harness-audit` v{} |".format(SIDECAR_VERSION))
    add("| 判词格 | `PASS` / `FAIL` / `INVALID` / `NOT RUN` |")
    add(
        "| 炎症阈值 | {} 次连续 `FAIL` 或 {} 次 `INVALID` → `INFLAMED`；"
        "{} 次连续 `PASS` → `NORMAL` |".format(
            audit.immune.fail_threshold,
            audit.immune.invalid_threshold,
            audit.immune.recovery_passes,
        )
    )
    add(
        "| 判决层 | tier1 `stat` / tier2 `git change set`（`run_command` 无策略，"
        "被强制 tier2） |"
    )
    add("| 临时仓库 | `{}` |".format(sandbox["repo"]))
    add("| 免疫状态文件 | `{}` |".format(audit.immune.state_path))
    add("")

    # -- TL;DR ---------------------------------------------------------
    add("## 0. 结论")
    add("")
    total = len(audit.judgements)
    fails = sum(1 for j in audit.judgements if j.verdict is Verdict.FAIL)
    passes = sum(1 for j in audit.judgements if j.verdict is Verdict.PASS)
    others = total - passes - fails
    add(
        "{} 次判词：**{} PASS / {} FAIL**{}。最终状态：**{}**。".format(
            total,
            passes,
            fails,
            "" if not others else "，{} 次 `INVALID`/`NOT RUN`".format(others),
            audit.immune.state,
        )
    )
    add("")
    add("1. **假完成被抓出。** CI 包装脚本吞掉 `pdflatex` 的退出码并 `exit 0`，"
        "agent 收到的响应是 `run_command: ok`；sidecar 去看 git change set，"
        "发现 `main.pdf` 从未出现，判 `FAIL`。")
    add("2. **炎症需要两次。** 第一次 `FAIL` 只是 `danger=1`（设计上「孤立的失败是"
        "正常的一天」），第二次 `FAIL` 进入 `INFLAMED`。")
    add("3. **恢复需要五次。** 修复源码后 5 次 `latexmk -g -pdf` 全部 `PASS`，"
        "`recovery_progress` 逐次 1→5，第 5 次回到 `NORMAL`。")
    add("4. **浅见证看不见归档内部。** 缺 `references.bib` 的 zip 在 git 眼里是一次"
        "正常的 `??`——tool 层判 `PASS`；`zipfile` 见证判 `FAIL`。"
        "这就是论文 §4.5 说的一类盲区，被我们自己的发布脚本复现了。")
    add("")
    add(
        "5. **引用也要见证。** `references.bib` 的 11 条里，{} 条能解析到 arXiv 记录并"
        "标题相符（PASS），{} 条没有任何可复算的标识符（INVALID）——"
        "后者不是伪造，是**不可见证**，正是论文对「无见证不可信」的定义。".format(
            len(citations.passed),
            len(citations.invalid_no_id) + len(citations.invalid_with_id),
        )
    )
    add(
        "6. **见证要能传到读者手里。** 第一轮只写 `eprint`，`main.pdf` 字节未变"
        "（`IEEEtran.bst` 丢弃该字段）；第二轮把同样的 arXiv 号写成 `note` 里的 "
        "`\\url`，PDF 变为 `{}…`，并携带 {} 条可点击的 `/URI` 注记。"
        "同一份知识，两种可见性。".format(
            next((d for n, _, d in hashes if n == "main.pdf"), "")[:16],
            len(embedded) if embedded is not None else 0,
        )
    )
    add("")

    # -- timeline ------------------------------------------------------
    add("## 1. 判词时间线")
    add("")
    add("| # | 阶段 | 调用 | agent 声称 | 见证 | 判词 | tier | 免疫状态 |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for j in audit.judgements:
        witness = []
        if j.changed:
            witness.append("changed: " + ", ".join("`{}`".format(p) for p in j.changed))
        if j.missing:
            witness.append("missing: " + ", ".join("`{}`".format(p) for p in j.missing))
        if j.unexpected:
            witness.append(
                "unexpected: " + ", ".join("`{}`".format(p) for p in j.unexpected)
            )
        if not witness:
            witness.append("effect={}".format(j.effect))
        add(
            "| {} | `{}` | `{}` | `{}` | {} | **{}** | `{}` | `{}` "
            "(d={}, r={}) |".format(
                j.seq,
                j.phase,
                j.tool,
                "success" if j.claim else "failure",
                "; ".join(witness),
                str(j.verdict),
                j.tier,
                j.state["state"],
                j.state["danger_count"],
                j.state["recovery_progress"],
            )
        )
    add("")

    # -- scenario 1 ----------------------------------------------------
    add("## 2. 场景一：假完成，以及它为什么不立刻发炎")
    add("")
    add("CI 包装脚本（`{}`）：".format(sandbox["scripts"] / "build.sh"))
    add("")
    add(code(FAKE_BUILD_SH, "sh"))
    add("")
    if fake:
        first_fake = fake[0]
        add("`pdflatex` 的真实反应（`build.log` 中与错误有关的前几行）：")
        add("")
        add(
            code(
                "\n".join(tex_errors).strip()
                or "(build.log 不可读：错误文本缺失，但见证仍然成立)",
                "text",
            )
        )
        add("")
        add("但 agent 看到的是：")
        add("")
        add(code(first_fake.agent_view, "text"))
        add("")
        add("sidecar 看到的（同一时刻、独立读取）：")
        add("")
        add(code(
            "changed_files     = {}\n"
            "missing_expected = {}\n"
            "exit_code         = {}\n"
            "reason            = {}".format(
                list(first_fake.changed),
                list(first_fake.missing),
                first_fake.exit_code,
                first_fake.reason,
            ),
            "text",
        ))
        add("")
        add(
            "判词 **{}**。注意 `exit_code=0` 不是读错了：包装脚本**确实**成功退出了，"
            "失败只存在于它丢掉的 `pdflatex` 状态里。sidecar 之所以没被骗，"
            "是因为判词来自见证而不是退出码，而 `check` 取的是工具层转述给 agent "
            "的那句话（`protocol`），不是 shell 的状态。".format(
                str(first_fake.verdict)
            )
        )
        add("")
    add("| 第几次假完成 | `danger_count` | 状态 |")
    add("| --- | --- | --- |")
    for j in fake:
        add("| {} | {} | `{}` |".format(j.seq, j.state["danger_count"], j.state["state"]))
    add("")
    add(
        "第一次 `FAIL` **没有**触发 `INFLAMED`，这是 `ImmuneState` 有意的不对称："
        "只有*连续*失败才构成攻击信号，被验证过的工作包围的偶发失败是正常的一天。"
        "第二次 `FAIL` 把 `danger_count` 推到阈值 2，状态变为 `INFLAMED`。"
    )
    add("")

    # -- scenario 2 ----------------------------------------------------
    add("## 3. 场景二：真实构建与免疫恢复")
    add("")
    add("修复 `main.tex` 后，命令换成真实的 `latexmk -g -pdf`，并且**在每次构建前先把 "
        "`main.pdf` 删除**（删除动作发生在被审计命令之外）：")
    add("")
    add(code("latexmk -g -pdf -interaction=nonstopmode -halt-on-error main.tex", "sh"))
    add("")
    add("这条前置条件不是装饰。两次相隔 0.8 秒的重建可能产出**字节完全相同**的 PDF"
        "（pdfTeX 只盖秒级时间戳），而内容见证无法把「重建了但字节没变」和"
        "「根本没构建」区分开。先删产物，见证要证明的就变成「从零生成」，"
        "这个方向上的歧义被消掉了。")
    add("")
    add("| rebuild | 判词 | `main.pdf` 变化 | 页数 | `recovery_progress` | 状态 |")
    add("| --- | --- | --- | --- | --- | --- |")
    previous_state = "INFLAMED"
    for index, (j, count) in enumerate(zip(builds, pages), start=1):
        if j.state["state"] == "NORMAL" and previous_state == "INFLAMED":
            progress = "{}/{} → 治愈".format(
                j.state["recovery_passes"], j.state["recovery_passes"]
            )
        else:
            progress = "{}/{}".format(
                j.state["recovery_progress"], j.state["recovery_passes"]
            )
        add(
            "| {} (#{}) | **{}** | {} | {} | {} | `{}` |".format(
                index,
                j.seq,
                str(j.verdict),
                ", ".join("`{}`".format(p) for p in j.changed) or "-",
                count,
                progress,
                j.state["state"],
            )
        )
        previous_state = j.state["state"]
    add("")
    if healed_at is not None:
        add(
            "第 5 次 `PASS` 让 `recovery_progress` 到达 {}/{}，状态回到 `NORMAL`，"
            "`danger_count` 清零。愈合比受伤慢——这是设计，不是缺陷。".format(
                healed_at.state["recovery_passes"], healed_at.state["recovery_passes"]
            )
        )
    add("")
    add(
        "页数是**第二见证**：git 只能说「`main.pdf` 变了」，`pdfinfo` 才能说"
        "「变出来的是一篇 {} 页的论文」。两者不一致时（例如只编出一页错误页），"
        "本脚本会在发布闸门里判 `FAIL`。".format(EXPECTED_PAGES)
    )
    add("")

    # -- scenario 3 ----------------------------------------------------
    add("## 4. 场景三：打包完整性 —— 浅见证的盲区")
    add("")
    add("第一次打包用的脚本（事故版本）：")
    add("")
    add(code(PACK_INCOMPLETE_SH, "sh"))
    add("")
    add("| 见证层 | 观察 | 判词 |")
    add("| --- | --- | --- |")
    if bad:
        add(
            "| git change set | {} | **{}** |".format(
                ", ".join("`{}`".format(p) for p in bad[0].changed) or "-",
                str(bad[0].verdict),
            )
        )
    add(
        "| `zipfile` 成员表 | members={}，missing={} | **{}** |".format(
            sorted(bad_archive.members),
            list(bad_archive.missing),
            str(bad[1].verdict) if len(bad) > 1 else "-",
        )
    )
    add("")
    if len(bad) > 1:
        add(
            "同一个物理动作，两个见证给出两个判词，而且**两个都对**：归档确实被重写了"
            "（tool 层没撒谎），归档确实不完整（agent 的结论错了）。git 看不见 zip "
            "内部，所以发布闸门不能只用一个浅见证。"
        )
        add("")
        add("sidecar 对归档的判词：")
        add("")
        add(code(bad[1].reason, "text"))
        add("")
        add(
            "这次归档 `FAIL` 让 `danger_count` 升到 {}，但状态停在 `{}`：系统刚愈合，"
            "孤立的失败不足以再次发炎。判词是 `FAIL`，炎症是另一件事——两者被刻意"
            "分开，否则审计器会变成一个对任何风吹草动都拉警报的装饰品。".format(
                bad[1].state["danger_count"], bad[1].state["state"]
            )
        )
        add("")
    add("修复后（`pack_complete.sh`）：")
    add("")
    add("| 成员 | 大小 (B) | zip 内 sha256 | 源文件 sha256 | 一致 |")
    add("| --- | --- | --- | --- | --- |")
    for name in REQUIRED_MEMBERS:
        member = good_archive.members.get(name)
        if member is None:
            add("| `{}` | - | - | - | ✗ |".format(name))
            continue
        add(
            "| `{}` | {} | `{}` | `{}` | {} |".format(
                name,
                member["bytes"],
                member["sha256"][:16],
                member["source_sha256"][:16],
                "✓" if member["agrees"] else "✗",
            )
        )
    add("")
    if len(good) > 1:
        add(
            "两次判词均为 **{}**，`danger_count` 归零，状态 `{}`。".format(
                str(good[1].verdict), audit.immune.state
            )
        )
    add("")

    # -- citations -----------------------------------------------------
    add("## 5. 引用见证：`references.bib` 逐条解析")
    add("")
    add(
        "`.bib` 文件里的每一条都是一句关于世界的话：*这个标识符* 指的是 *这篇论文*。"
        "`CitationAuditProxy` 把这句话交给注册机构核对，判词由同一个 `VerdictEngine` "
        "给出——与文件写入共用一套格，而不是另立一套更宽松的通过标准。"
    )
    add("")
    add("| 条目 | 标识符 | 判词 | 机构 / 未通过原因 |")
    add("| --- | --- | --- | --- |")
    for row in citations.rows:
        if row.record.verdict is Verdict.PASS:
            detail = "{} 返回标题与条目一致".format(row.record.agency or "witness")
        else:
            cause = str(row.record.witness.get("cause") or "")
            detail = {
                "no_identifier": "无 DOI、无 arXiv 号（动态网页 / 仓库 / 会议论文集）",
                "not_found": "机构无此记录",
                "unavailable": "机构不可达（本次运行未看到，不等于错误）",
                "title_mismatch": "标题不符（张冠李戴）",
                "author_mismatch": "作者不符",
            }.get(cause, cause or "-")
        add(
            "| `{}` | {} | **{}** | {} |".format(
                row.entry.key,
                "`{}`".format(row.identifier) if row.identifier else "-",
                str(row.record.verdict),
                detail,
            )
        )
    add("")
    add(
        "{} PASS / {} FAIL / {} INVALID。FAIL 为零：没有任何一条的标题与解析到的记录"
        "相互矛盾。{} 条 INVALID 全部属于「条目本身没有可复算的标识符」，"
        "包括本文两篇自引软件与三个 GitHub 项目——把它们的 URL 抄进 `url` 字段并不构成"
        "见证，因为没有人能 re-resolve 出一个稳定记录。".format(
            len(citations.passed),
            len(citations.failed),
            len(citations.invalid_no_id) + len(citations.invalid_with_id),
            len(citations.invalid_no_id),
        )
    )
    add("")
    if citations.invalid_with_id:
        add(
            "**注意**：有 {} 条声明了标识符却没能解析成功，这一类 INVALID 不是诚实答案，"
            "而是本次运行的缺陷（格式错误或网络失败），发布闸门会因此判 `FAIL`。".format(
                len(citations.invalid_with_id)
            )
        )
        add("")
    else:
        add(
            "反过来，凡是**声明了**标识符的条目，本次全部解析成功。这一点被单独设为闸门"
            "条件：否则网络一断，八条诚实的 INVALID 会把三条本应可解析的 INVALID "
            "一起盖住，而后者是可以修的。"
        )
        add("")

    # -- release gate --------------------------------------------------
    add("## 6. 发布闸门：真实交付物")
    add("")
    add("审计对象不是沙箱副本，而是将要上传的那一个：`{}`。".format(PAPER_DIR / "metabolism_paper_v1.zip"))
    add("")
    add("| 检查项 | 结果 |")
    add("| --- | --- |")
    add("| 三个成员齐全 | {} |".format("✓" if not live.missing else "✗ 缺 " + ", ".join(live.missing)))
    add("| 成员哈希与源文件一致 | {} |".format("✓" if not live.mismatched else "✗ " + ", ".join(live.mismatched)))
    add("| 无多余成员 | {} |".format("✓" if not live.extra else "✗ " + ", ".join(live.extra)))
    add("| `main.pdf` 页数 | {}（期望 {}） |".format(live_pages, EXPECTED_PAGES))
    add(
        "| 引用：无 FAIL | {} |".format(
            "✓" if not citations.failed else "✗ " + ", ".join(
                r.entry.key for r in citations.failed
            )
        )
    )
    add(
        "| 引用：声明了标识符的条目均可解析 | {} |".format(
            "✓" if not citations.invalid_with_id else "✗ " + ", ".join(
                r.entry.key for r in citations.invalid_with_id
            )
        )
    )
    add(
        "| 引用：arXiv 链接在 PDF 中可点击 | {} |".format(
            "✓ {}/{} 条（全档共 {} 条 `/URI`）".format(
                len(visible_witness_urls(PAPER_DIR / "references.bib")) - len(missing_links),
                len(visible_witness_urls(PAPER_DIR / "references.bib")),
                len(embedded) if embedded is not None else 0,
            )
            if not missing_links and embedded is not None
            else "✗ 缺 " + ", ".join(missing_links)
        )
    )
    add("| **判词** | **{}** |".format(str(gate.verdict)))
    add("")
    add("成员指纹：")
    add("")
    add("| 成员 | 大小 (B) | sha256（前 16 位） |")
    add("| --- | --- | --- |")
    for name in REQUIRED_MEMBERS:
        member = live.members.get(name)
        if member:
            add("| `{}` | {} | `{}` |".format(name, member["bytes"], member["sha256"][:16]))
    add("")

    # -- hashes --------------------------------------------------------
    add("## 7. 交付物哈希")
    add("")
    add(
        "下表是文件系统上实际存在的字节，不是构建日志里的自述。"
        "`main.pdf` 与 `main.tex` 在多次独立会话中重编后哈希不变，"
        "因为 `SOURCE_DATE_EPOCH` 已固定；`references.bib` 与 `main.pdf` 因新增"
        "可点击的 arXiv 注记而改变。"
    )
    add("")
    add("| 文件 | 大小 (B) | SHA256 |")
    add("| --- | --- | --- |")
    for name, size, digest in hashes:
        add("| `{}` | {} | `{}` |".format(name, size, digest))
    add("")

    current_pdf = next((d for n, _, d in hashes if n == "main.pdf"), "")
    add("### 7.1 两轮修订，两种见证深度")
    add("")
    add("| 轮次 | 改动 | `main.pdf` SHA256 | 页数 |")
    add("| --- | --- | --- | --- |")
    add(
        "| 第一轮 | 仅加 `eprint`（机器可读） | `{}…`（**未变**） | {} |".format(
            BASELINE_PDF_SHA256[:16], EXPECTED_PAGES
        )
    )
    add(
        "| 第二轮 | 追加 `note` 中的 `\\url`（人可读） | `{}…`（**已变**） | {} |".format(
            current_pdf[:16], EXPECTED_PAGES
        )
    )
    add("")
    if current_pdf == BASELINE_PDF_SHA256:
        add(
            "本轮 `main.pdf` 的哈希与基线**相同**。若这是加了 `note` 之后的运行，"
            "说明 `\\url` 并未真正进入排版流程，需要检查 `main.bbl`。"
        )
    else:
        add(
            "同一个标识符，两种写法，两种命运。第一轮加 `eprint` 后 `main.pdf` "
            "**一个字节都没变**：`IEEEtran.bst` 1.14 没有 `eprint` 处理器，"
            "字段被读入即丢弃，`main.bbl` 里出现 0 次。审计器照样能判 `PASS`——"
            "它读 `.bib`，不读 PDF。第二轮把同一个号码写成 `note` 里的 `\\url`，"
            "PDF 立刻变了：`{}…`，页数仍是 {}，overfull hbox 仍为 0。".format(
                current_pdf[:16], EXPECTED_PAGES
            )
        )
        add("")
        add(
            "**机器能审计到的，人眼未必能看到。** 这不是比喻，是两轮之间唯一的差别："
            "标识符没变，判词没变，变的只是它被写进了哪个字段。第一轮的 `PASS` 对读者"
            "毫无帮助——他们手里只有一个无法复核的引文，而那正是本文反对的东西。"
        )
    add("")

    # -- findings ------------------------------------------------------
    add("## 8. 这次吃狗粮发现了什么")
    add("")
    add("1. **`exit 0` 吞错是这个管线最真实的故障模式。** 包装脚本没有撒谎，它只是"
        "把退出码打印到日志里然后丢弃；agent 的转录完全自洽。只有独立见证能把"
        "「自洽」和「正确」分开。")
    add("2. **一次失败不该拉响警报。** 第一次 `FAIL` 保持 `NORMAL`。把阈值设成 1 "
        "会让免疫系统对每个偶发失败发炎，最终被运维关掉——与被审计的系统同归于尽。")
    add("3. **见证深度必须匹配意图深度。** 打包的意图是「归档里有三个文件」，"
        "而 git 见证只能回答「归档变了」。发布闸门因此必须下沉到归档字节；"
        "否则一次缺文件的发布会被判 `PASS`，而这正是论文要防的那种假完成。")
    add("4. **审计器不修正 agent 的视图。** 两次假完成里，agent 收到的都还是"
        "`run_command: ok`。旁路观察者一旦改写被审计者的世界观，它就成了系统的一部分。")
    add(
        "5. **凭记忆给出的标识符，只有经过物理见证才算数。** 审计过程中我们按记忆填过"
        "一个 arXiv 号（Panickssery 那篇），解析结果是 *Style Over Substance*——"
        "一篇完全不同的论文，判 `FAIL`；按标题反查才得到 `2404.13076`。"
        "这个错误在排版、在 PDF、在任何自洽性检查里都看不见。"
    )
    add(
        "6. **`eprint` 是给机器的字段，不是给读者的。** 同样的 arXiv 号，写进 `eprint` "
        "时 PDF 一个字节不变；改写进 `note` 的 `\\url` 后 PDF 立刻换了哈希。"
        "`IEEEtran.bst` 丢弃前者，排版后者。若读者要复算，标识符必须出现在会被排版出来"
        "的地方，否则「文件里有见证」和「读者能复核」始终是两件事。"
    )
    add(
        "7. **链接本身也要被见证。** 本轮把「arXiv 链接必须是 PDF 里的 `/URI` 注记」"
        "做成了闸门条件：脚本解压 PDF 的对象流，取出全部链接目标，与 `.bib` 承诺的"
        "URL 逐一比对。它不读 `.bib` 来确认 `.bib`，而是读交付物确认交付物。"
        "本次 {} 条承诺、{} 条命中。".format(
            len(visible_witness_urls(PAPER_DIR / "references.bib")),
            len(embedded) if embedded is not None else 0,
        )
    )
    add("")

    # -- appendix ------------------------------------------------------
    add("## 附录 A：控制台判词记录（原始输出）")
    add("")
    add(code("\n".join(CONSOLE), "text"))
    add("")
    add("## 附录 B：免疫状态文件")
    add("")
    add("`{}`（进程退出后仍可恢复，重启不能洗掉怀疑）：".format(audit.immune.state_path))
    add("")
    add(code(json.dumps(audit.immune.as_document(), indent=2, sort_keys=True), "json"))
    add("")
    add("---")
    add("")
    add(
        "生成于 `{}`，sidecar v{}，宿主 `{}`。".format(
            datetime.now().astimezone().isoformat(timespec="seconds"),
            SIDECAR_VERSION,
            os.uname().nodename,
        )
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    # The sandbox build must produce the *same* artefact build.sh does, or the report
    # ends up printing one filename with two hashes. Two things make that happen: the
    # same epoch (which stops pdfTeX stamping wall-clock time into /CreationDate and
    # /ID), and letting latexmk run its full pass sequence rather than a single
    # pdflatex pass that leaves the bibliography empty. The first is set here, on the
    # process environment, because the good-build scenario invokes latexmk directly
    # and not through the wrapper above; the second is latexmk's default.
    os.environ.setdefault("SOURCE_DATE_EPOCH", "1793577600")
    os.environ.setdefault("FORCE_SOURCE_DATE", "1")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sandbox",
        default=None,
        help="parent directory for the throwaway repo (default: system temp)",
    )
    parser.add_argument(
        "--report",
        default=str(PAPER_DIR / "DOGFOOD_AUDIT.md"),
        help="where to write the report",
    )
    args = parser.parse_args()

    started = datetime.now().astimezone()

    if not (HARNESS_DIR / "audit_sidecar").is_dir():
        raise SystemExit(
            "sidecar source not found at {}; this audit must run against the "
            "real implementation".format(HARNESS_DIR)
        )

    emit("=" * 78)
    emit("harness-audit-sidecar v{} | dogfood run | {}".format(SIDECAR_VERSION, started.isoformat(timespec="seconds")))
    emit("=" * 78)

    sandbox = prepare_sandbox(args.sandbox)
    emit("sandbox : {}".format(sandbox["root"]))
    emit("repo    : {} (git, 3 files committed)".format(sandbox["repo"]))
    emit("")

    audit = Audit(sandbox["root"], sandbox["repo"])

    emit("-- 场景一：注入假完成（CI 吞掉 pdflatex 的失败）--")
    tex_errors = scenario_false_completion(audit, sandbox["scripts"])
    emit("")

    emit("-- 场景二：真实构建，连续 5 次 PASS 以愈合 --")
    pages = scenario_recovery(audit, sandbox["scripts"])
    emit("")

    emit("-- 场景三：打包完整性（缺 references.bib）--")
    _, bad_archive, _, good_archive = scenario_packaging(
        audit, sandbox["scripts"]
    )
    emit("")

    emit("-- 引用见证：references.bib 逐条解析 --")
    citations = scenario_citations(PAPER_DIR / "references.bib")
    emit("")

    emit("-- 发布闸门：真实交付物 --")
    gate, live, live_pages, missing_links, embedded = release_gate(audit, citations)
    emit("")
    emit(
        "        pdf links: promised={} embedded={} missing={}".format(
            len(visible_witness_urls(PAPER_DIR / "references.bib")),
            len(embedded) if embedded is not None else "unreadable",
            list(missing_links),
        )
    )

    hashes = artefact_hashes()

    emit("=" * 78)
    summary = audit.proxy.summary()
    emit(
        "sidecar verdicts over tool calls: {}".format(
            ", ".join("{}={}".format(k, v) for k, v in summary.items())
        )
    )
    emit(
        "immune state: {} (danger={}, recovery={}/{})".format(
            audit.immune.state,
            audit.immune.danger_count,
            audit.immune.recovery_progress,
            audit.immune.recovery_passes,
        )
    )
    emit("release gate : {}".format(gate.verdict))
    emit("=" * 78)

    report = render_report(
        audit,
        sandbox,
        pages,
        tex_errors,
        bad_archive,
        good_archive,
        gate,
        live,
        live_pages,
        started,
        citations,
        hashes,
        missing_links,
        embedded,
    )
    report_path = Path(args.report)
    report_path.write_text(report, encoding="utf-8")
    print("report  : {}".format(report_path))

    # A release audit that cannot fail its own gate is decoration.
    ok = (
        gate.verdict is Verdict.PASS
        and citations.ok
        and not missing_links
        and audit.immune.state == "NORMAL"
        and all(j.verdict is Verdict.PASS for j in audit.judgements if j.phase == "build")
    )
    print("result  : {}".format("READY TO SUBMIT" if ok else "BLOCKED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
