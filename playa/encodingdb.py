import logging
import re
from typing import Dict, Iterable, Optional, Union

from playa.encodings import (
    MAC_EXPERT_ENCODING,
    MAC_ROMAN_ENCODING,
    STANDARD_ENCODING,
    WIN_ANSI_ENCODING,
)
from playa.glyphlist import glyphname2unicode
from playa.parser import PSLiteral, PDFObject

HEXADECIMAL = re.compile(r"[0-9a-fA-F]+")

log = logging.getLogger(__name__)


def name2unicode(name: str) -> str:
    """Converts Adobe glyph names to Unicode strings using the algorithm
    described in the Adobe Glyph List Specification.

    Specification: https://github.com/adobe-type-tools/agl-specification#2-the-mapping

    Adobe Glyph List and Adobe Glyph List for New Fonts:
    https://github.com/adobe-type-tools/agl-aglfn/

    Returns:
       A Unicode string of one or more characters, or the empty string
       if the glyph name cannot be matched (including the case of invalid
       Unicode scalar values in the range D800 to DFFF).
    """
    name = name.split(".")[0]
    components = name.split("_")

    if len(components) > 1:
        return "".join(map(name2unicode, components))
    elif name in glyphname2unicode:
        return glyphname2unicode[name]
    elif name.startswith("uni"):
        name_without_uni = name.strip("uni")
        if HEXADECIMAL.match(name_without_uni) and len(name_without_uni) % 4 == 0:
            unicode_digits = [
                int(name_without_uni[i : i + 4], base=16)
                for i in range(0, len(name_without_uni), 4)
            ]
            return "".join(
                chr(digit) for digit in unicode_digits if not (0xD800 <= digit < 0xE000)
            )
    elif name.startswith("u"):
        name_without_u = name.strip("u")
        if HEXADECIMAL.match(name_without_u) and 4 <= len(name_without_u) <= 6:
            unicode_digit = int(name_without_u, base=16)
            if 0xD800 <= unicode_digit < 0xE000:
                return ""
            return chr(unicode_digit)
    return ""


class EncodingDB:
    encodings = {
        # NOTE: According to PDF 1.7 Annex D.1, "Conforming readers
        # shall not have a predefined encoding named
        # StandardEncoding", but it's not clear why not.
        "StandardEncoding": STANDARD_ENCODING,
        "MacRomanEncoding": MAC_ROMAN_ENCODING,
        "WinAnsiEncoding": WIN_ANSI_ENCODING,
        "MacExpertEncoding": MAC_EXPERT_ENCODING,
    }

    @classmethod
    def get_encoding(
        cls,
        base: Union[PSLiteral, Dict[int, str], None] = None,
        diff: Optional[Iterable[PDFObject]] = None,
    ) -> Dict[int, str]:
        if base is None:
            encoding = {}
        elif isinstance(base, PSLiteral):
            encoding = cls.encodings.get(base.name, {})
        else:
            encoding = base
        if diff is not None:
            encoding = encoding.copy()
            cid = 0
            for x in diff:
                if isinstance(x, int):
                    cid = x
                elif isinstance(x, PSLiteral):
                    encoding[cid] = x.name
                    cid += 1
        return encoding


def cid2unicode_from_encoding(encoding: Dict[int, str]) -> Dict[int, str]:
    cid2unicode = {}
    for cid, name in encoding.items():
        uni = name2unicode(name)
        if uni != "":
            cid2unicode[cid] = uni
    return cid2unicode
