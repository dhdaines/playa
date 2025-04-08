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
    """Converts Adobe glyph names to Unicode numbers.

    In contrast to the specification, this raises a KeyError instead of return
    an empty string when the key is unknown.
    This way the caller must explicitly define what to do
    when there is not a match.

    Reference:
    https://github.com/adobe-type-tools/agl-specification#2-the-mapping

    :returns unicode character if name resembles something,
    otherwise a KeyError
    """
    if not isinstance(name, str):
        raise KeyError(
            'Could not convert unicode name "%s" to character because '
            "it should be of type str but is of type %s" % (name, type(name)),
        )

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
            for digit in unicode_digits:
                raise_key_error_for_invalid_unicode(digit)
            characters = map(chr, unicode_digits)
            return "".join(characters)

    elif name.startswith("u"):
        name_without_u = name.strip("u")

        if HEXADECIMAL.match(name_without_u) and 4 <= len(name_without_u) <= 6:
            unicode_digit = int(name_without_u, base=16)
            raise_key_error_for_invalid_unicode(unicode_digit)
            return chr(unicode_digit)

    raise KeyError(
        'Could not convert unicode name "%s" to character because '
        "it does not match specification" % name,
    )


def raise_key_error_for_invalid_unicode(unicode_digit: int) -> None:
    """Unicode values should not be in the range D800 through DFFF because
    that is used for surrogate pairs in UTF-16

    :raises KeyError if unicode digit is invalid
    """
    if 55295 < unicode_digit < 57344:
        raise KeyError(
            "Unicode digit %d is invalid because "
            "it is in the range D800 through DFFF" % unicode_digit,
        )


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
        try:
            cid2unicode[cid] = name2unicode(name)
        except (KeyError, ValueError) as e:
            log.debug("Failed to get char %s: %s", name, e)
    return cid2unicode
