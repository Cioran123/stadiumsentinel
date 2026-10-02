"""Render a lower-third PNG for the review reel (called by src/app/api/reel/route.ts).

    python pipeline/label_card.py OUT.png "line 1" "line 2" ...

OpenCV's Hershey fonts are ASCII-only, so non-ASCII characters are replaced.
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

from media import render_label_png

REPLACE = {"\u2014": "-", "\u2013": "-", "\u00b7": "|", "\u2019": "'", "\u00b0": " deg"}


def ascii_only(s: str) -> str:
    for k, v in REPLACE.items():
        s = s.replace(k, v)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    out = Path(sys.argv[1])
    lines = [ascii_only(line)[:120] for line in sys.argv[2:]]
    render_label_png(lines, out)


if __name__ == "__main__":
    main()
