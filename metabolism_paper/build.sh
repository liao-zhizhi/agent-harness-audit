#!/usr/bin/env bash
#
# Compile metabolism_paper/main.pdf and gate the result.
#
#   ./build.sh          compile, verify, print the hash
#   ./build.sh --check  verify the committed PDF only (no rebuild)
#
# Why this exists, and why it is new:
#
# The first two papers in this series already had this wrapper (agent_audit/release/
# build/build.sh and the EquivSVA arxiv_build/build_pdf.sh) for one reason: a recorded
# SHA256 is worthless if the same sources produce a different file each run. This paper
# was built by hand with `latexmk -pdf main.tex`, which lets pdfTeX write the current
# time into /CreationDate and a fresh /ID. Two compiles of identical sources gave two
# hashes, so the hash in DOGFOOD_AUDIT.md and in the release zip could not be reproduced
# by anyone -- including us, a day later. Pinning SOURCE_DATE_EPOCH fixes both, exactly
# as the sibling scripts do.
#
# 1793577600 = 2026-11-02 00:00:00 UTC, the date the references were last read. It must
# not be earlier than the newest cited source, or the PDF would claim to predate a
# document it cites.
#
# The metadata gate is here for the same reason it is in the sibling scripts: hyperref
# does not copy \title into /Title, so a PDF can look complete on the page and still be
# indexed as untitled. That is the failure this paper audits, so it is checked, not
# assumed.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PDF="$HERE/main.pdf"
LOG="$HERE/main.log"

export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1793577600}"
export FORCE_SOURCE_DATE=1

CHECK_ONLY=0
case "${1:-}" in
  --check) CHECK_ONLY=1 ;;
  "") ;;
  *) echo "usage: $0 [--check]" >&2; exit 2 ;;
esac

if [ "$CHECK_ONLY" -eq 0 ]; then
  echo "== compiling with pdfLaTeX (epoch $SOURCE_DATE_EPOCH)"
  # -g: force a rebuild even if latexmk thinks the .pdf is current, so the hash always
  # describes the sources in front of it rather than an earlier run's leftovers.
  ( cd "$HERE" && latexmk -pdf -g -interaction=nonstopmode -halt-on-error main.tex >/dev/null 2>&1 ) || {
    echo "ERROR: latexmk failed; tail of log:" >&2
    tail -30 "$LOG" >&2
    exit 1
  }
fi

fail=0

echo "== verifying"
n=$(grep -c 'Overfull \\hbox' "$LOG" || true)
printf '  overfull hbox        : %s (must be 0)\n' "$n"
[ "$n" -eq 0 ] || { echo "    FAIL: content overflows the text block" >&2; fail=1; }

n=$(grep -ciE 'Citation .* undefined|There were undefined citations' "$LOG" || true)
printf '  undefined citations  : %s (must be 0)\n' "$n"
[ "$n" -eq 0 ] || { echo "    FAIL: a \\cite has no matching bib entry" >&2; fail=1; }

n=$(grep -c 'Missing character' "$LOG" || true)
printf '  missing characters   : %s (must be 0)\n' "$n"
[ "$n" -eq 0 ] || { echo "    FAIL: glyphs dropped" >&2; fail=1; }

n=$(pdfinfo "$PDF" | awk '/^Pages:/ {print $2}')
printf '  pages                : %s (must be > 1)\n' "$n"
[ "${n:-0}" -gt 1 ] || { echo "    FAIL: single-page output" >&2; fail=1; }

ttl=$(pdfinfo "$PDF" | sed -n 's/^Title:[[:space:]]*//p')
ath=$(pdfinfo "$PDF" | sed -n 's/^Author:[[:space:]]*//p')
printf '  /Title               : %s\n' "${ttl:-<empty>}"
printf '  /Author              : %s\n' "${ath:-<empty>}"
[ -n "$ttl" ] || { echo "    FAIL: PDF /Title is empty" >&2; fail=1; }
[ -n "$ath" ] || { echo "    FAIL: PDF /Author is empty" >&2; fail=1; }

if [ "$fail" -ne 0 ]; then
  echo "ERROR: verification failed." >&2
  exit 1
fi

echo
sha256sum "$PDF" | sed "s|$HERE/||"
