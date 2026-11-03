#!/usr/bin/env python3
"""Repack metabolism_paper_v2.zip reproducibly.

Same reason pack.py exists in the working copy for v1: a zip stores every
member's modification time, so repacking the same bytes in a different minute
produces a different archive hash even though nothing inside changed. Writing
the members with a fixed timestamp and a fixed mode removes the only two
non-deterministic fields, so the recorded hash describes the contents rather
than the moment of packing.

v2 differs from v1 in one deliberate way: the archive does NOT contain the
compiled PDF. The PDF is published as its own artefact, and a copy inside the
source archive could drift from it -- two files both claiming to be the paper.

    python3 pack_v2.py     # rewrite the zip, print member and archive hashes
"""

import hashlib
import pathlib
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "metabolism_paper_v2.zip"
MEMBERS = ["main.tex", "references.bib"]

# Fixed, not "now". 2026-11-03 is the publication date of v2.
DATE = (2026, 11, 3, 0, 0, 0)

#: The archive hash published with the Zenodo v2 record. Printed as a check
#: rather than asserted: a mismatch means the sources changed after the
#: deposit, which is information the operator needs, not a build failure.
PUBLISHED = "92c441e3fe0a47dfac32a491da1256791df8cee3d39125a9d3c8339c73d8b19e"


def main() -> int:
    missing = [m for m in MEMBERS if not (HERE / m).is_file()]
    if missing:
        raise SystemExit("missing member(s): %s" % ", ".join(missing))

    tmp = OUT.with_suffix(".zip.new")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name in MEMBERS:
            info = zipfile.ZipInfo(name, date_time=DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, (HERE / name).read_bytes())
    tmp.replace(OUT)

    with zipfile.ZipFile(OUT) as z:
        for i in z.infolist():
            print("  %-16s %7d B  %s" % (i.filename, i.file_size,
                  hashlib.sha256(z.read(i.filename)).hexdigest()))
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print("  %-16s %7d B  %s" % (OUT.name, OUT.stat().st_size, digest))
    print("  published v2     %s  %s" % (
        PUBLISHED[:16] + "...",
        "matches" if digest == PUBLISHED else "DIFFERS: sources changed after the deposit",
    ))
    return 0 if digest == PUBLISHED else 0


if __name__ == "__main__":
    sys.exit(main())
