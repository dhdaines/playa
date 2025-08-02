"""
Convert an AFM file to Python font metrics.
"""

import fileinput
from pathlib import Path
from typing import Dict, TextIO


def convert_font_metrics(fh: TextIO) -> None:
    """Convert AFM files to a mapping of font metrics."""
    fonts = {}
    for line in fh:
        f = line.strip().split(" ")
        if not f:
            continue
        k = f[0]
        if k == "FontName":
            fontname = f[1]
            props = {"FontName": fontname, "Flags": 0}
            chars: Dict[int, int] = {}
            fonts[fontname] = (props, chars)
        elif k == "C":
            cid = int(f[1])
            if 0 <= cid and cid <= 255:
                width = int(f[4])
                chars[cid] = width
        elif k in ("CapHeight", "XHeight", "ItalicAngle", "Ascender", "Descender"):
            k = {"Ascender": "Ascent", "Descender": "Descent"}.get(k, k)
            props[k] = float(f[1])
        elif k in ("FontName", "FamilyName", "Weight"):
            k = {"FamilyName": "FontFamily", "Weight": "FontWeight"}.get(k, k)
            props[k] = f[1]
        elif k == "IsFixedPitch":
            if f[1].lower() == "true":
                props["Flags"] = 64
        elif k == "FontBBox":
            props[k] = tuple(map(float, f[1:5]))
    print("# -*- python -*-")
    print("from typing import Any, Dict, Tuple")
    print("FONT_METRICS: Dict[str, Tuple[Dict[str, Any], Dict[str, int]]] = {")
    for fontname, (props, chars) in fonts.items():
        print(f" {fontname!r}: {(props, chars)!r},")
    print("}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("afms", nargs="+", type=Path, help="AFM files to convert")
    args = parser.parse_args()
    with fileinput.input(args.afms) as fh:
        convert_font_metrics(fh)


if __name__ == "__main__":
    main()
