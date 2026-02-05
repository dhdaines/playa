"""
Convert an AFM file to Python font metrics.
"""

import fileinput
from pathlib import Path
from typing import Dict, TextIO

from playa.glyphlist import glyphname2unicode


def convert_font_metrics(fh: TextIO, outfh: TextIO) -> None:
    """Convert AFM files to a mapping of font metrics."""
    fonts = {}
    for line in fh:
        f = line.strip().split(" ")
        if not f:
            continue
        k = f[0]
        if k == "FontName":
            fontname = f[1].encode("latin-1")
            props = {"FontName": fontname, "Flags": 0}
            chars: Dict[str, int] = {}
            fonts[f[1]] = (props, chars)
        elif k == "C":
            cid = int(f[1])
            glyph = f[7]
            width = int(f[4])
            if glyph in glyphname2unicode:
                uni = glyphname2unicode[glyph]
            elif fontname == b"ZapfDingbats" and glyph[0] == "a":
                # FIXME: This is, really, not correct, but the whole
                # enterprise is corrupt (see
                # playa.font.Type1Font._glyph_space_width)
                uni = chr(int(glyph[1:]))
            else:
                uni = chr(cid)
            chars[uni] = width
        elif k in ("CapHeight", "XHeight", "ItalicAngle", "Ascender", "Descender"):
            k = {"Ascender": "Ascent", "Descender": "Descent"}.get(k, k)
            props[k] = float(f[1])
        elif k in ("FontName", "FamilyName", "Weight"):
            k = {"FamilyName": "FontFamily", "Weight": "FontWeight"}.get(k, k)
            props[k] = f[1].encode("latin-1")
        elif k == "IsFixedPitch":
            if f[1].lower() == "true":
                props["Flags"] = 64
        elif k == "FontBBox":
            props[k] = [float(x) for x in f[1:5]]
    print(
        '''"""Font metrics for the Adobe core 14 fonts.

Font metrics are used to compute the boundary of each character
written with a proportional font.

The following data were extracted from the AFM files:

  http://www.ctan.org/tex-archive/fonts/adobe/afm/
"""

#  BEGIN Verbatim copy of the license part
#
# Adobe Core 35 AFM Files with 314 Glyph Entries - ReadMe
#
# This file and the 35 PostScript(R) AFM files it accompanies may be
# used, copied, and distributed for any purpose and without charge,
# with or without modification, provided that all copyright notices
# are retained; that the AFM files are not distributed without this
# file; that all modifications to this file or any of the AFM files
# are prominently noted in the modified file(s); and that this
# paragraph is not modified. Adobe Systems has no responsibility or
# obligation to support the use of the AFM files.
#
#  END Verbatim copy of the license part

from typing import Dict, Tuple
from playa.pdftypes import PDFObject

FONT_METRICS: Dict[str, Tuple[Dict[str, PDFObject], Dict[str, int]]] = {
''',
        file=outfh,
    )
    for fontname, (props, chars) in fonts.items():
        print(f" {fontname!r}: {(props, chars)!r},", file=outfh)
    print(
        """}

# Aliases defined in implementation note 62 in Appecix H. related to section 5.5.1
# (Type 1 Fonts) in the PDF Reference.
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
FONT_METRICS["TimesNewRoman,BoldItalic"] = FONT_METRICS["Times-BoldItalic"]
""",
        file=outfh,
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("afms", nargs="+", type=Path, help="AFM files to convert")
    parser.add_argument(
        "-o", "--outfile", type=argparse.FileType("w"), help="Output file"
    )
    args = parser.parse_args()
    with fileinput.input(args.afms) as fh:
        convert_font_metrics(fh, args.outfile)


if __name__ == "__main__":
    main()
