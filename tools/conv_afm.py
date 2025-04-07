"""Convert AFM files to Python code for fontmetrics.py."""

import tarfile
from pathlib import Path
from typing import Dict, BinaryIO


def str2num(s: str) -> float:
    kf = float(s)
    ki = int(kf)
    return ki if ki == kf else kf


def convert_font_metrics(fh: BinaryIO) -> None:
    """Convert an AFM file to a mapping of font metrics.

    See below for the output.
    """
    fonts = {}
    for line in fh:
        f = line.strip().decode("ascii").split()
        if not f:
            continue
        k = f[0]
        if k == "FontName":
            fontname = f[1]
            props = {"FontName": fontname, "Flags": 0}
            chars: Dict[int, float] = {}
            glyphs: Dict[str, float] = {}
            fonts[fontname] = (props, chars)
        elif k == "C":
            cid = int(f[1])
            if cid == -1:
                name = f[7]
                glyphs[name] = str2num(f[4])
            else:
                chars[cid] = str2num(f[4])
        elif k in ("CapHeight", "XHeight", "ItalicAngle", "Ascender", "Descender"):
            k = {"Ascender": "Ascent", "Descender": "Descent"}.get(k, k)
            props[k] = str2num(f[1])
        elif k in ("FontName", "FamilyName", "Weight"):
            k = {"FamilyName": "FontFamily", "Weight": "FontWeight"}.get(k, k)
            props[k] = f[1]
        elif k == "IsFixedPitch":
            if f[1].lower() == "true":
                props["Flags"] = 64
        elif k == "FontBBox":
            props[k] = tuple(map(float, f[1:5]))
    for fontname, (props, chars) in fonts.items():
        print(f" {fontname!r}: {(props, chars, glyphs)!r},")


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("afmtar", type=Path, help="Tar archive with AFM files.")
    args = parser.parse_args()

    with tarfile.open(args.afmtar) as tar:
        print(
            """\
# Downloaded from:
# https://mirrors.ctan.org/fonts/adobe/afm/Adobe-Core35_AFMs-314.tar.gz

# This file and the 35 PostScript(R) AFM files it accompanies may be
# used, copied, and distributed for any purpose and without charge,
# with or without modification, provided that all copyright notices
# are retained; that the AFM files are not distributed without this
# file; that all modifications to this file or any of the AFM files
# are prominently noted in the modified file(s); and that this
# paragraph is not modified. Adobe Systems has no responsibility or
# obligation to support the use of the AFM files.

from typing import Any, Dict, Tuple, Union
FONT_METRICS: Dict[str,
    Tuple[Dict[str, Union[float, str, tuple]],
          Dict[int, float],
          Dict[str, float],
]] = {"""
        )
        for info in tar:
            path = Path(info.path)
            if path.suffix.lower() == ".afm":
                convert_font_metrics(tar.extractfile(info))
        print(
            """\
}

# Aliases defined in Appendix H, section 5.5.1, implementation
# note 62 (Type 1 Fonts) in the PDF Reference, 6th edition (but not
# the ISO standard)

FONT_METRICS["Arial"] = FONT_METRICS["Helvetica"]
FONT_METRICS["Arial,Italic"] = FONT_METRICS["Helvetica-Oblique"]
FONT_METRICS["Arial,Bold"] = FONT_METRICS["Helvetica-Bold"]
FONT_METRICS["Arial,BoldItalic"] = FONT_METRICS["Helvetica-BoldOblique"]
FONT_METRICS["CourierNew"] = FONT_METRICS["Courier"]
FONT_METRICS["CourierNew,Italic"] = FONT_METRICS["Courier-Oblique"]
FONT_METRICS["CourierNew,Bold"] = FONT_METRICS["Courier-Bold"]
FONT_METRICS["CourierNew,BoldItalic"] = FONT_METRICS["Courier-BoldOblique"]
FONT_METRICS["TimesNewRoman"] = FONT_METRICS["Times-Roman"]
FONT_METRICS["TimesNewRoman,Italic"] = FONT_METRICS["Times-Italic"]
FONT_METRICS["TimesNewRoman,Bold"] = FONT_METRICS["Times-Bold"]
FONT_METRICS["TimesNewRoman,BoldItalic"] = FONT_METRICS["Times-BoldItalic"]"""
        )


if __name__ == "__main__":
    main()
