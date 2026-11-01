#!/usr/bin/env bash
#
# Rebuild draft_final.pdf from draft_final.md, then verify the result.
#
#   ./build/build.sh            rebuild, verify, refresh PDF + .sha256
#   ./build/build.sh --check    verify the committed PDF only, do not rebuild
#
# Exits non-zero if any check fails, so this is safe to wire into CI.

set -euo pipefail

BUILD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="$(dirname "$BUILD_DIR")"
SRC="$RELEASE_DIR/draft_final.md"
OUT="$RELEASE_DIR/draft_final.pdf"
SUM="$RELEASE_DIR/draft_final.sha256"

CHECK_ONLY=0
case "${1:-}" in
  --check) CHECK_ONLY=1 ;;
  "") ;;
  *) echo "usage: $0 [--check]" >&2; exit 2 ;;
esac

# A fixed timestamp makes the PDF byte-identical on every rebuild, which is what
# lets the recorded SHA256 mean something. Without it, /CreationDate changes on
# each run and the checksum is a moving target.
#
# 1793491200 = 2026-11-01 00:00:00 UTC, which is the access date the manuscript
# itself states for every source in Appendix C ("All sources were read on
# 2026-11-01"). It must not be earlier than the most recent cited source, or the
# PDF would claim to predate a document it cites. Do not lower it; raising it to
# a later date is fine, but changes the hash recorded in BUILD.md.
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1793491200}"
export FORCE_SOURCE_DATE=1

for tool in pandoc xelatex pdfinfo pdftotext sha256sum python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: '$tool' not found in PATH" >&2; exit 1; }
done
[ -f "$SRC" ] || { echo "ERROR: missing $SRC" >&2; exit 1; }

# ---------------------------------------------------------------------------
# verify <pdf>  -- the gate. Everything here was a real defect at some point.
# ---------------------------------------------------------------------------
verify() {
  local pdf="$1" log="$2" fail=0

  if [ -n "$log" ] && [ -f "$log" ]; then
    # Long code lines and wide tables that escaped the layout.
    local overfull
    overfull=$(grep -c 'Overfull \\hbox' "$log" || true)
    # Characters XeTeX silently dropped -- the tofu detector.
    local missing
    missing=$(grep -c 'Missing character' "$log" || true)
    printf '  overfull hbox        : %s (must be 0)\n' "$overfull"
    printf '  missing characters   : %s (must be 0)\n' "$missing"
    [ "$overfull" -eq 0 ] || { echo "    FAIL: content overflows the text block" >&2; fail=1; }
    [ "$missing" -eq 0 ] || { echo "    FAIL: glyphs dropped (CJK font or symbol fallback)" >&2; fail=1; }
  fi

  local pages
  pages=$(pdfinfo "$pdf" | awk '/^Pages:/ {print $2}')
  printf '  pages                : %s (must be > 1)\n' "$pages"
  [ "${pages:-0}" -gt 1 ] || { echo "    FAIL: single-page output" >&2; fail=1; }

  local tc pct
  tc=$(pdftotext "$pdf" - | grep -c 'Task Completed' || true)
  pct=$(pdftotext "$pdf" - | grep -c '65.4%' || true)
  printf '  "Task Completed"     : %s (must be > 0)\n' "$tc"
  printf '  "65.4%%"             : %s (must be > 0)\n' "$pct"
  [ "$tc" -gt 0 ] || { echo "    FAIL: body text missing from PDF" >&2; fail=1; }
  [ "$pct" -gt 0 ] || { echo "    FAIL: empirical figure missing from PDF" >&2; fail=1; }

  # The Chinese abstract is the part most likely to become tofu.
  local zh
  zh=$(pdftotext "$pdf" - | grep -c '假完成' || true)
  printf '  Chinese abstract     : %s (must be > 0)\n' "$zh"
  [ "$zh" -gt 0 ] || { echo "    FAIL: Chinese text not extractable" >&2; fail=1; }

  return "$fail"
}

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "== verifying existing $OUT"
  verify "$OUT" ""
  echo
  echo "== recorded checksum"
  ( cd "$RELEASE_DIR" && sha256sum -c draft_final.sha256 )
  exit 0
fi

echo "== building"
echo "  source : $SRC"
echo "  epoch  : $SOURCE_DATE_EPOCH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Title and author are taken from the document itself so they cannot drift.
python3 - "$SRC" "$WORK/body.md" "$WORK/meta.yaml" <<'PY'
import json, re, sys

src, body_out, meta_out = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src, encoding="utf-8") as fh:
    lines = fh.read().splitlines()

if not lines or not lines[0].startswith("# "):
    sys.exit("ERROR: first line of the source is not an H1 title")
title = lines[0][2:].strip()


def smart_quotes(s):
    """Mirror pandoc's smart punctuation for straight quotes.

    The H1 is written with ASCII quotes; pandoc renders them as curly in the
    body, so the metadata title must be converted too or the title bar and the
    printed title disagree.
    """
    out, dq, sq = [], 0, 0
    for i, ch in enumerate(s):
        if ch == '"':
            out.append("\u201c" if dq % 2 == 0 else "\u201d")
            dq += 1
        elif ch == "'":
            prev = s[i - 1] if i else ""
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if prev.isalnum() and nxt.isalnum():
                out.append("\u2019")          # apostrophe, e.g. "doesn't"
            else:
                out.append("\u2018" if sq % 2 == 0 else "\u2019")
                sq += 1
        else:
            out.append(ch)
    return "".join(out)


title = smart_quotes(title)

author = ""
for line in lines[1:12]:
    m = re.match(r"\*\*Author:\*\*\s*(.+)", line)
    if m:
        # "liaozhizhi (Liao) · mail" -> keep the name, drop the contact
        author = m.group(1).split("·")[0].strip()
        author = author.replace("（", " (").replace("）", ")")
        break

# Drop the H1: it becomes \title{}, and leaving it in would print the title
# twice (title block + body heading).
with open(body_out, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines[1:]) + "\n")

with open(meta_out, "w", encoding="utf-8") as fh:
    fh.write("title: " + json.dumps(title, ensure_ascii=False) + "\n")
    if author:
        fh.write("author: " + json.dumps(author, ensure_ascii=False) + "\n")

print(f"  title  : {title[:70]}")
print(f"  author : {author}")
PY

pandoc "$WORK/body.md" \
  --from=markdown \
  --to=latex \
  --standalone \
  --lua-filter="$BUILD_DIR/fixes.lua" \
  --include-in-header="$BUILD_DIR/header.tex" \
  --metadata-file="$WORK/meta.yaml" \
  --toc --toc-depth=2 \
  -V documentclass=article \
  -V colorlinks=false \
  -o "$WORK/paper.tex"

# pandoc escapes straight ASCII quotes inside \hypersetup{pdftitle=...}, so the
# viewer title bar would read ``False Completion''. Put the real string back.
python3 - "$WORK/paper.tex" "$WORK/meta.yaml" <<'PY'
import json, re, sys

tex_path, meta_path = sys.argv[1], sys.argv[2]
title = json.loads(open(meta_path, encoding="utf-8").readline().split(":", 1)[1])
tex = open(tex_path, encoding="utf-8").read()
new, n = re.subn(r"pdftitle=\{[^}]*\}", "pdftitle={" + title + "}", tex, count=1)
if n != 1:
    sys.exit("ERROR: could not locate pdftitle in generated .tex")
open(tex_path, "w", encoding="utf-8").write(new)
PY

# Two passes: the TOC and \ref labels need the first pass' .aux.
for pass in 1 2; do
  echo "  xelatex pass $pass"
  ( cd "$WORK" && xelatex -interaction=nonstopmode -halt-on-error paper.tex > "run$pass.out" 2>&1 ) || {
    echo "ERROR: xelatex failed on pass $pass; tail of log:" >&2
    tail -30 "$WORK/run$pass.out" >&2
    exit 1
  }
done

echo
echo "== verifying"
if ! verify "$WORK/paper.pdf" "$WORK/paper.log"; then
  echo >&2
  echo "ERROR: verification failed; $OUT was left untouched." >&2
  exit 1
fi

echo
echo "== publishing"
cp "$WORK/paper.pdf" "$OUT"
( cd "$RELEASE_DIR" && sha256sum draft_final.pdf > draft_final.sha256 )
printf '  wrote %s\n' "$OUT"
printf '  wrote %s\n' "$SUM"
cat "$SUM" | sed 's/^/  /'
