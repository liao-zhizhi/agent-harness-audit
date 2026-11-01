# Rebuilding `draft_final.pdf`

`draft_final.md` is the source of record; `draft_final.pdf` is generated from it.
Nothing in the PDF is hand-edited, so a rebuild is always safe.

```
./build/build.sh            # rebuild, verify, refresh PDF + .sha256
./build/build.sh --check    # verify the committed PDF only (no rebuild)
```

`--check` exits non-zero if the PDF on disk no longer matches `draft_final.sha256`,
or if any structural check below fails. Both modes are CI-safe.

## Layout

```
release/
├── draft_final.md          source of record
├── draft_final.pdf         generated artifact
├── draft_final.sha256      checksum of the artifact
├── BUILD.md                this file
└── build/
    ├── build.sh            one-shot pandoc + XeLaTeX + verification
    ├── header.tex          LaTeX preamble (fonts, tables, code wrapping)
    └── fixes.lua           pandoc filter (table column widths, URL breaking)
```

`build/` is normally ignored by `.gitignore` (the Python sdist convention). The
three sources are explicitly whitelisted at the end of that file so they travel
with the published artifact instead of being silently excluded.

## Toolchain

| Component | Version |
| --- | --- |
| pandoc | 3.9 |
| XeLaTeX | XeTeX 3.141592653-2.6-0.999998 (TeX Live 2026) |
| OS | Ubuntu 24.04.5 LTS |
| Body text | Noto Serif / Noto Serif CJK SC |
| Headings | Noto Sans / Noto Sans CJK SC |
| Code | Noto Sans Mono / Noto Sans Mono CJK SC |

Chinese glyphs come from `NotoSerifCJK-Regular.ttc` and
`NotoSansCJK-Regular.ttc` in `/usr/share/fonts/opentype/noto/`.
`fonts-noto-cjk` supplies them on Debian/Ubuntu.

Fonts are addressed by family name (`Noto Serif CJK SC`). Note that `.ttc`
collections report the collection's first face name (`NotoSerifCJKjp`) in
`pdffonts` output; that is a labelling artefact of the collection, not an
indication that the Japanese face was used. The simplified-Chinese forms are
what actually render.

## Reproducible output

`build.sh` pins `SOURCE_DATE_EPOCH=1793491200` and `FORCE_SOURCE_DATE=1`, so
`/CreationDate` and the trailer `/ID` are fixed and two consecutive builds are
byte-identical:

```
$ ./build/build.sh && cat draft_final.sha256
26db3f1b392daafd3de93c21878baec871d3ad2704405519a93467ea6ca97e8f  draft_final.pdf
$ ./build/build.sh && cat draft_final.sha256
26db3f1b392daafd3de93c21878baec871d3ad2704405519a93467ea6ca97e8f  draft_final.pdf
```

Without the pinned epoch the timestamp changes on every run and the checksum
would be meaningless.

**Why that particular timestamp.** `1793491200` is 2026-11-01 00:00:00 UTC, which
is the date the manuscript itself states as the access date for every source in
Appendix C ("All sources were read on 2026-11-01"). The constraint is that the
PDF must not claim to have been created before a document it cites: a fixed
epoch of, say, 2025-01-01 or 2026-01-01 would put `/CreationDate` months or
years ahead of sources dated 2026-11-01, which a careful reader could notice.
So `CreationDate` reads `2026-11-01` — the same day as the access date, not the
actual render time of any particular copy.

Changing this value changes the PDF hash. If you do raise it, rebuild, then
update the hash in this file and the reproducible-output block above.

To reproduce the recorded hash, build on the toolchain versions listed above.

## Verification performed on every build

`build.sh` refuses to publish a PDF that fails any of these:

| Check | Command | Expected |
| --- | --- | --- |
| Content overflows the text block | `grep -c 'Overfull \hbox'` on the log | `0` |
| Characters silently dropped | `grep -c 'Missing character'` on the log | `0` |
| Multi-page output | `pdfinfo` → `Pages` | `> 1` (currently 25) |
| Body text present | `pdftotext … \| grep -c 'Task Completed'` | `> 0` (currently 3) |
| Empirical figure present | `pdftotext … \| grep -c '65.4%'` | `> 0` (currently 6) |
| Chinese text present | `pdftotext … \| grep -c '假完成'` | `> 0` (currently 3) |

The first two are the important ones. `Missing character` is the tofu detector:
XeTeX drops an absent glyph without raising an error, so a broken font mapping
produces a PDF that looks fine in a thumbnail and is missing text when read.

## The three layout hazards, and what handles them

**CJK glyphs.** `header.tex` sets all six faces explicitly, including
`\setCJKmonofont`. Without the mono face, Chinese inside `\texttt` disappears.

**Table breaking.** The 17 pipe tables declare no column widths, and pandoc
would lay them out at natural width, running past the margin. `fixes.lua`
derives each column's width from the actual cell contents — total length for
balance, longest unbreakable word as a hard floor — and renormalises to exactly
1.0. Tables become `longtable`, so long ones break across pages with the header
repeated.

**Code and URL overflow.** `fvextra` with `breaklines` and `breakanywhere`,
applied to pandoc's `Highlighting` environment as well as plain verbatim.
URLs in the source appendix are 117 characters and cannot break under
`\texttt`, so `fixes.lua` rewrites them to `\url` and the preamble loads
`xurl` to allow a break at any character.

## Known cosmetic note

`pdftotext -bbox` shows ~159 words whose right edge sits up to 1.75 pt past the
right edge of the text block (0.6 mm). This is microtype character protrusion,
the normal typographic technique of letting punctuation hang slightly into the
margin. It is not content overflow, which is why `Overfull \hbox` is 0.

## Table of contents

The PDF carries a two-level table of contents (`--toc --toc-depth=2`), which is
appropriate at 25 pages. To match the Markdown exactly, drop those two flags in
`build.sh` and rebuild.
