import logging
import re
from typing import Dict, Iterable, Optional, Union

from playa.glyphlist import glyphname2unicode
from playa.parser import PSLiteral

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


STANDARD_ENCODING = {65: 'A', 225: 'AE', 66: 'B', 67: 'C', 68: 'D', 69: 'E', 70: 'F', 71: 'G', 72: 'H', 73: 'I', 74: 'J', 75: 'K', 76: 'L', 232: 'Lslash', 77: 'M', 78: 'N', 79: 'O', 234: 'OE', 233: 'Oslash', 80: 'P', 81: 'Q', 82: 'R', 83: 'S', 84: 'T', 85: 'U', 86: 'V', 87: 'W', 88: 'X', 89: 'Y', 90: 'Z', 97: 'a', 194: 'acute', 241: 'ae', 38: 'ampersand', 94: 'asciicircum', 126: 'asciitilde', 42: 'asterisk', 64: 'at', 98: 'b', 92: 'backslash', 124: 'bar', 123: 'braceleft', 125: 'braceright', 91: 'bracketleft', 93: 'bracketright', 198: 'breve', 183: 'bullet', 99: 'c', 207: 'caron', 203: 'cedilla', 162: 'cent', 195: 'circumflex', 58: 'colon', 44: 'comma', 168: 'currency', 100: 'd', 178: 'dagger', 179: 'daggerdbl', 200: 'dieresis', 36: 'dollar', 199: 'dotaccent', 245: 'dotlessi', 101: 'e', 56: 'eight', 188: 'ellipsis', 208: 'emdash', 177: 'endash', 61: 'equal', 33: 'exclam', 161: 'exclamdown', 102: 'f', 174: 'fi', 53: 'five', 175: 'fl', 166: 'florin', 52: 'four', 164: 'fraction', 103: 'g', 251: 'germandbls', 193: 'grave', 62: 'greater', 171: 'guillemotleft', 187: 'guillemotright', 172: 'guilsinglleft', 173: 'guilsinglright', 104: 'h', 205: 'hungarumlaut', 45: 'hyphen', 105: 'i', 106: 'j', 107: 'k', 108: 'l', 60: 'less', 248: 'lslash', 109: 'm', 197: 'macron', 110: 'n', 57: 'nine', 35: 'numbersign', 111: 'o', 250: 'oe', 206: 'ogonek', 49: 'one', 227: 'ordfeminine', 235: 'ordmasculine', 249: 'oslash', 112: 'p', 182: 'paragraph', 40: 'parenleft', 41: 'parenright', 37: 'percent', 46: 'period', 180: 'periodcentered', 189: 'perthousand', 43: 'plus', 113: 'q', 63: 'question', 191: 'questiondown', 34: 'quotedbl', 185: 'quotedblbase', 170: 'quotedblleft', 186: 'quotedblright', 96: 'quoteleft', 39: 'quoteright', 184: 'quotesinglbase', 169: 'quotesingle', 114: 'r', 202: 'ring', 115: 's', 167: 'section', 59: 'semicolon', 55: 'seven', 54: 'six', 47: 'slash', 32: 'space', 163: 'sterling', 116: 't', 51: 'three', 196: 'tilde', 50: 'two', 117: 'u', 95: 'underscore', 118: 'v', 119: 'w', 120: 'x', 121: 'y', 165: 'yen', 122: 'z', 48: 'zero'}
MAC_ROMAN_ENCODING = {65: 'A', 174: 'AE', 231: 'Aacute', 229: 'Acircumflex', 128: 'Adieresis', 203: 'Agrave', 129: 'Aring', 204: 'Atilde', 66: 'B', 67: 'C', 130: 'Ccedilla', 68: 'D', 69: 'E', 131: 'Eacute', 230: 'Ecircumflex', 232: 'Edieresis', 233: 'Egrave', 70: 'F', 71: 'G', 72: 'H', 73: 'I', 234: 'Iacute', 235: 'Icircumflex', 236: 'Idieresis', 237: 'Igrave', 74: 'J', 75: 'K', 76: 'L', 77: 'M', 78: 'N', 132: 'Ntilde', 79: 'O', 206: 'OE', 238: 'Oacute', 239: 'Ocircumflex', 133: 'Odieresis', 241: 'Ograve', 175: 'Oslash', 205: 'Otilde', 80: 'P', 81: 'Q', 82: 'R', 83: 'S', 84: 'T', 85: 'U', 242: 'Uacute', 243: 'Ucircumflex', 134: 'Udieresis', 244: 'Ugrave', 86: 'V', 87: 'W', 88: 'X', 89: 'Y', 217: 'Ydieresis', 90: 'Z', 97: 'a', 135: 'aacute', 137: 'acircumflex', 171: 'acute', 138: 'adieresis', 190: 'ae', 136: 'agrave', 38: 'ampersand', 140: 'aring', 94: 'asciicircum', 126: 'asciitilde', 42: 'asterisk', 64: 'at', 139: 'atilde', 98: 'b', 92: 'backslash', 124: 'bar', 123: 'braceleft', 125: 'braceright', 91: 'bracketleft', 93: 'bracketright', 249: 'breve', 165: 'bullet', 99: 'c', 255: 'caron', 141: 'ccedilla', 252: 'cedilla', 162: 'cent', 246: 'circumflex', 58: 'colon', 44: 'comma', 169: 'copyright', 219: 'currency', 100: 'd', 160: 'dagger', 224: 'daggerdbl', 161: 'degree', 172: 'dieresis', 214: 'divide', 36: 'dollar', 250: 'dotaccent', 245: 'dotlessi', 101: 'e', 142: 'eacute', 144: 'ecircumflex', 145: 'edieresis', 143: 'egrave', 56: 'eight', 201: 'ellipsis', 209: 'emdash', 208: 'endash', 61: 'equal', 33: 'exclam', 193: 'exclamdown', 102: 'f', 222: 'fi', 53: 'five', 223: 'fl', 196: 'florin', 52: 'four', 218: 'fraction', 103: 'g', 167: 'germandbls', 96: 'grave', 62: 'greater', 199: 'guillemotleft', 200: 'guillemotright', 220: 'guilsinglleft', 221: 'guilsinglright', 104: 'h', 253: 'hungarumlaut', 45: 'hyphen', 105: 'i', 146: 'iacute', 148: 'icircumflex', 149: 'idieresis', 147: 'igrave', 106: 'j', 107: 'k', 108: 'l', 60: 'less', 194: 'logicalnot', 109: 'm', 248: 'macron', 181: 'mu', 110: 'n', 202: 'space', 57: 'nine', 150: 'ntilde', 35: 'numbersign', 111: 'o', 151: 'oacute', 153: 'ocircumflex', 154: 'odieresis', 207: 'oe', 254: 'ogonek', 152: 'ograve', 49: 'one', 187: 'ordfeminine', 188: 'ordmasculine', 191: 'oslash', 155: 'otilde', 112: 'p', 166: 'paragraph', 40: 'parenleft', 41: 'parenright', 37: 'percent', 46: 'period', 225: 'periodcentered', 228: 'perthousand', 43: 'plus', 177: 'plusminus', 113: 'q', 63: 'question', 192: 'questiondown', 34: 'quotedbl', 227: 'quotedblbase', 210: 'quotedblleft', 211: 'quotedblright', 212: 'quoteleft', 213: 'quoteright', 226: 'quotesinglbase', 39: 'quotesingle', 114: 'r', 168: 'registered', 251: 'ring', 115: 's', 164: 'section', 59: 'semicolon', 55: 'seven', 54: 'six', 47: 'slash', 32: 'space', 163: 'sterling', 116: 't', 51: 'three', 247: 'tilde', 170: 'trademark', 50: 'two', 117: 'u', 156: 'uacute', 158: 'ucircumflex', 159: 'udieresis', 157: 'ugrave', 95: 'underscore', 118: 'v', 119: 'w', 120: 'x', 121: 'y', 216: 'ydieresis', 180: 'yen', 122: 'z', 48: 'zero'}
WIN_ANSI_ENCODING = {65: 'A', 198: 'AE', 193: 'Aacute', 194: 'Acircumflex', 196: 'Adieresis', 192: 'Agrave', 197: 'Aring', 195: 'Atilde', 66: 'B', 67: 'C', 199: 'Ccedilla', 68: 'D', 69: 'E', 201: 'Eacute', 202: 'Ecircumflex', 203: 'Edieresis', 200: 'Egrave', 208: 'Eth', 128: 'Euro', 70: 'F', 71: 'G', 72: 'H', 73: 'I', 205: 'Iacute', 206: 'Icircumflex', 207: 'Idieresis', 204: 'Igrave', 74: 'J', 75: 'K', 76: 'L', 77: 'M', 78: 'N', 209: 'Ntilde', 79: 'O', 140: 'OE', 211: 'Oacute', 212: 'Ocircumflex', 214: 'Odieresis', 210: 'Ograve', 216: 'Oslash', 213: 'Otilde', 80: 'P', 81: 'Q', 82: 'R', 83: 'S', 138: 'Scaron', 84: 'T', 222: 'Thorn', 85: 'U', 218: 'Uacute', 219: 'Ucircumflex', 220: 'Udieresis', 217: 'Ugrave', 86: 'V', 87: 'W', 88: 'X', 89: 'Y', 221: 'Yacute', 159: 'Ydieresis', 90: 'Z', 142: 'Zcaron', 97: 'a', 225: 'aacute', 226: 'acircumflex', 180: 'acute', 228: 'adieresis', 230: 'ae', 224: 'agrave', 38: 'ampersand', 229: 'aring', 94: 'asciicircum', 126: 'asciitilde', 42: 'asterisk', 64: 'at', 227: 'atilde', 98: 'b', 92: 'backslash', 124: 'bar', 123: 'braceleft', 125: 'braceright', 91: 'bracketleft', 93: 'bracketright', 166: 'brokenbar', 149: 'bullet', 99: 'c', 231: 'ccedilla', 184: 'cedilla', 162: 'cent', 136: 'circumflex', 58: 'colon', 44: 'comma', 169: 'copyright', 164: 'currency', 100: 'd', 134: 'dagger', 135: 'daggerdbl', 176: 'degree', 168: 'dieresis', 247: 'divide', 36: 'dollar', 101: 'e', 233: 'eacute', 234: 'ecircumflex', 235: 'edieresis', 232: 'egrave', 56: 'eight', 133: 'ellipsis', 151: 'emdash', 150: 'endash', 61: 'equal', 240: 'eth', 33: 'exclam', 161: 'exclamdown', 102: 'f', 53: 'five', 131: 'florin', 52: 'four', 103: 'g', 223: 'germandbls', 96: 'grave', 62: 'greater', 171: 'guillemotleft', 187: 'guillemotright', 139: 'guilsinglleft', 155: 'guilsinglright', 104: 'h', 45: 'hyphen', 105: 'i', 237: 'iacute', 238: 'icircumflex', 239: 'idieresis', 236: 'igrave', 106: 'j', 107: 'k', 108: 'l', 60: 'less', 172: 'logicalnot', 109: 'm', 175: 'macron', 181: 'mu', 215: 'multiply', 110: 'n', 160: 'space', 57: 'nine', 241: 'ntilde', 35: 'numbersign', 111: 'o', 243: 'oacute', 244: 'ocircumflex', 246: 'odieresis', 156: 'oe', 242: 'ograve', 49: 'one', 189: 'onehalf', 188: 'onequarter', 185: 'onesuperior', 170: 'ordfeminine', 186: 'ordmasculine', 248: 'oslash', 245: 'otilde', 112: 'p', 182: 'paragraph', 40: 'parenleft', 41: 'parenright', 37: 'percent', 46: 'period', 183: 'periodcentered', 137: 'perthousand', 43: 'plus', 177: 'plusminus', 113: 'q', 63: 'question', 191: 'questiondown', 34: 'quotedbl', 132: 'quotedblbase', 147: 'quotedblleft', 148: 'quotedblright', 145: 'quoteleft', 146: 'quoteright', 130: 'quotesinglbase', 39: 'quotesingle', 114: 'r', 174: 'registered', 115: 's', 154: 'scaron', 167: 'section', 59: 'semicolon', 55: 'seven', 54: 'six', 47: 'slash', 32: 'space', 173: 'space', 163: 'sterling', 116: 't', 254: 'thorn', 51: 'three', 190: 'threequarters', 179: 'threesuperior', 152: 'tilde', 153: 'trademark', 50: 'two', 178: 'twosuperior', 117: 'u', 250: 'uacute', 251: 'ucircumflex', 252: 'udieresis', 249: 'ugrave', 95: 'underscore', 118: 'v', 119: 'w', 120: 'x', 121: 'y', 253: 'yacute', 255: 'ydieresis', 165: 'yen', 122: 'z', 158: 'zcaron', 48: 'zero'}
MAC_EXPERT_ENCODING = {190: 'AEsmall', 135: 'Aacutesmall', 137: 'Acircumflexsmall', 39: 'Acutesmall', 138: 'Adieresissmall', 136: 'Agravesmall', 140: 'Aringsmall', 97: 'Asmall', 139: 'Atildesmall', 243: 'Brevesmall', 98: 'Bsmall', 174: 'Caronsmall', 141: 'Ccedillasmall', 201: 'Cedillasmall', 94: 'Circumflexsmall', 99: 'Csmall', 172: 'Dieresissmall', 250: 'Dotaccentsmall', 100: 'Dsmall', 142: 'Eacutesmall', 144: 'Ecircumflexsmall', 145: 'Edieresissmall', 143: 'Egravesmall', 101: 'Esmall', 68: 'Ethsmall', 102: 'Fsmall', 96: 'Gravesmall', 103: 'Gsmall', 104: 'Hsmall', 34: 'Hungarumlautsmall', 146: 'Iacutesmall', 148: 'Icircumflexsmall', 149: 'Idieresissmall', 147: 'Igravesmall', 105: 'Ismall', 106: 'Jsmall', 107: 'Ksmall', 194: 'Lslashsmall', 108: 'Lsmall', 244: 'Macronsmall', 109: 'Msmall', 110: 'Nsmall', 150: 'Ntildesmall', 207: 'OEsmall', 151: 'Oacutesmall', 153: 'Ocircumflexsmall', 154: 'Odieresissmall', 242: 'Ogoneksmall', 152: 'Ogravesmall', 191: 'Oslashsmall', 111: 'Osmall', 155: 'Otildesmall', 112: 'Psmall', 113: 'Qsmall', 251: 'Ringsmall', 114: 'Rsmall', 167: 'Scaronsmall', 115: 'Ssmall', 185: 'Thornsmall', 126: 'Tildesmall', 116: 'Tsmall', 156: 'Uacutesmall', 158: 'Ucircumflexsmall', 159: 'Udieresissmall', 157: 'Ugravesmall', 117: 'Usmall', 118: 'Vsmall', 119: 'Wsmall', 120: 'Xsmall', 180: 'Yacutesmall', 216: 'Ydieresissmall', 121: 'Ysmall', 189: 'Zcaronsmall', 122: 'Zsmall', 38: 'ampersandsmall', 129: 'asuperior', 245: 'bsuperior', 169: 'centinferior', 35: 'centoldstyle', 130: 'centsuperior', 58: 'colon', 123: 'colonmonetary', 44: 'comma', 178: 'commainferior', 248: 'commasuperior', 182: 'dollarinferior', 36: 'dollaroldstyle', 37: 'dollarsuperior', 235: 'dsuperior', 165: 'eightinferior', 56: 'eightoldstyle', 161: 'eightsuperior', 228: 'esuperior', 214: 'exclamdownsmall', 33: 'exclamsmall', 86: 'ff', 89: 'ffi', 90: 'ffl', 87: 'fi', 208: 'figuredash', 76: 'fiveeighths', 176: 'fiveinferior', 53: 'fiveoldstyle', 222: 'fivesuperior', 88: 'fl', 162: 'fourinferior', 52: 'fouroldstyle', 221: 'foursuperior', 47: 'fraction', 45: 'hyphen', 95: 'hypheninferior', 209: 'hyphensuperior', 233: 'isuperior', 241: 'lsuperior', 247: 'msuperior', 187: 'nineinferior', 57: 'nineoldstyle', 225: 'ninesuperior', 246: 'nsuperior', 43: 'onedotenleader', 74: 'oneeighth', 124: 'onefitted', 72: 'onehalf', 193: 'oneinferior', 49: 'oneoldstyle', 71: 'onequarter', 218: 'onesuperior', 78: 'onethird', 175: 'osuperior', 91: 'parenleftinferior', 40: 'parenleftsuperior', 93: 'parenrightinferior', 41: 'parenrightsuperior', 46: 'period', 179: 'periodinferior', 249: 'periodsuperior', 192: 'questiondownsmall', 63: 'questionsmall', 229: 'rsuperior', 125: 'rupiah', 59: 'semicolon', 77: 'seveneighths', 166: 'seveninferior', 55: 'sevenoldstyle', 224: 'sevensuperior', 164: 'sixinferior', 54: 'sixoldstyle', 223: 'sixsuperior', 32: 'space', 234: 'ssuperior', 75: 'threeeighths', 163: 'threeinferior', 51: 'threeoldstyle', 73: 'threequarters', 61: 'threequartersemdash', 220: 'threesuperior', 230: 'tsuperior', 42: 'twodotenleader', 170: 'twoinferior', 50: 'twooldstyle', 219: 'twosuperior', 79: 'twothirds', 188: 'zeroinferior', 48: 'zerooldstyle', 226: 'zerosuperior'}

PDF_DOC_ENCODING = {65: 'A', 198: 'AE', 193: 'Aacute', 194: 'Acircumflex', 196: 'Adieresis', 192: 'Agrave', 197: 'Aring', 195: 'Atilde', 66: 'B', 67: 'C', 199: 'Ccedilla', 68: 'D', 69: 'E', 201: 'Eacute', 202: 'Ecircumflex', 203: 'Edieresis', 200: 'Egrave', 208: 'Eth', 160: 'Euro', 70: 'F', 71: 'G', 72: 'H', 73: 'I', 205: 'Iacute', 206: 'Icircumflex', 207: 'Idieresis', 204: 'Igrave', 74: 'J', 75: 'K', 76: 'L', 149: 'Lslash', 77: 'M', 78: 'N', 209: 'Ntilde', 79: 'O', 150: 'OE', 211: 'Oacute', 212: 'Ocircumflex', 214: 'Odieresis', 210: 'Ograve', 216: 'Oslash', 213: 'Otilde', 80: 'P', 81: 'Q', 82: 'R', 83: 'S', 151: 'Scaron', 84: 'T', 222: 'Thorn', 85: 'U', 218: 'Uacute', 219: 'Ucircumflex', 220: 'Udieresis', 217: 'Ugrave', 86: 'V', 87: 'W', 88: 'X', 89: 'Y', 221: 'Yacute', 152: 'Ydieresis', 90: 'Z', 153: 'Zcaron', 97: 'a', 225: 'aacute', 226: 'acircumflex', 180: 'acute', 228: 'adieresis', 230: 'ae', 224: 'agrave', 38: 'ampersand', 229: 'aring', 94: 'asciicircum', 126: 'asciitilde', 42: 'asterisk', 64: 'at', 227: 'atilde', 98: 'b', 92: 'backslash', 124: 'bar', 123: 'braceleft', 125: 'braceright', 91: 'bracketleft', 93: 'bracketright', 24: 'breve', 166: 'brokenbar', 128: 'bullet', 99: 'c', 25: 'caron', 231: 'ccedilla', 184: 'cedilla', 162: 'cent', 26: 'circumflex', 58: 'colon', 44: 'comma', 169: 'copyright', 164: 'currency', 100: 'd', 129: 'dagger', 130: 'daggerdbl', 176: 'degree', 168: 'dieresis', 247: 'divide', 36: 'dollar', 27: 'dotaccent', 154: 'dotlessi', 101: 'e', 233: 'eacute', 234: 'ecircumflex', 235: 'edieresis', 232: 'egrave', 56: 'eight', 131: 'ellipsis', 132: 'emdash', 133: 'endash', 61: 'equal', 240: 'eth', 33: 'exclam', 161: 'exclamdown', 102: 'f', 147: 'fi', 53: 'five', 148: 'fl', 134: 'florin', 52: 'four', 135: 'fraction', 103: 'g', 223: 'germandbls', 96: 'grave', 62: 'greater', 171: 'guillemotleft', 187: 'guillemotright', 136: 'guilsinglleft', 137: 'guilsinglright', 104: 'h', 28: 'hungarumlaut', 45: 'hyphen', 105: 'i', 237: 'iacute', 238: 'icircumflex', 239: 'idieresis', 236: 'igrave', 106: 'j', 107: 'k', 108: 'l', 60: 'less', 172: 'logicalnot', 155: 'lslash', 109: 'm', 175: 'macron', 138: 'minus', 181: 'mu', 215: 'multiply', 110: 'n', 57: 'nine', 241: 'ntilde', 35: 'numbersign', 111: 'o', 243: 'oacute', 244: 'ocircumflex', 246: 'odieresis', 156: 'oe', 29: 'ogonek', 242: 'ograve', 49: 'one', 189: 'onehalf', 188: 'onequarter', 185: 'onesuperior', 170: 'ordfeminine', 186: 'ordmasculine', 248: 'oslash', 245: 'otilde', 112: 'p', 182: 'paragraph', 40: 'parenleft', 41: 'parenright', 37: 'percent', 46: 'period', 183: 'periodcentered', 139: 'perthousand', 43: 'plus', 177: 'plusminus', 113: 'q', 63: 'question', 191: 'questiondown', 34: 'quotedbl', 140: 'quotedblbase', 141: 'quotedblleft', 142: 'quotedblright', 143: 'quoteleft', 144: 'quoteright', 145: 'quotesinglbase', 39: 'quotesingle', 114: 'r', 174: 'registered', 30: 'ring', 115: 's', 157: 'scaron', 167: 'section', 59: 'semicolon', 55: 'seven', 54: 'six', 47: 'slash', 32: 'space', 163: 'sterling', 116: 't', 254: 'thorn', 51: 'three', 190: 'threequarters', 179: 'threesuperior', 31: 'tilde', 146: 'trademark', 50: 'two', 178: 'twosuperior', 117: 'u', 250: 'uacute', 251: 'ucircumflex', 252: 'udieresis', 249: 'ugrave', 95: 'underscore', 118: 'v', 119: 'w', 120: 'x', 121: 'y', 253: 'yacute', 255: 'ydieresis', 165: 'yen', 122: 'z', 158: 'zcaron', 48: 'zero'}

SYMBOL_BUILTIN_ENCODING = {32: 'space', 33: 'exclam', 34: 'universal', 35: 'numbersign', 36: 'existential', 37: 'percent', 38: 'ampersand', 39: 'suchthat', 40: 'parenleft', 41: 'parenright', 42: 'asteriskmath', 43: 'plus', 44: 'comma', 45: 'minus', 46: 'period', 47: 'slash', 48: 'zero', 49: 'one', 50: 'two', 51: 'three', 52: 'four', 53: 'five', 54: 'six', 55: 'seven', 56: 'eight', 57: 'nine', 58: 'colon', 59: 'semicolon', 60: 'less', 61: 'equal', 62: 'greater', 63: 'question', 64: 'congruent', 65: 'Alpha', 66: 'Beta', 67: 'Chi', 68: 'Delta', 69: 'Epsilon', 70: 'Phi', 71: 'Gamma', 72: 'Eta', 73: 'Iota', 74: 'theta1', 75: 'Kappa', 76: 'Lambda', 77: 'Mu', 78: 'Nu', 79: 'Omicron', 80: 'Pi', 81: 'Theta', 82: 'Rho', 83: 'Sigma', 84: 'Tau', 85: 'Upsilon', 86: 'sigma1', 87: 'Omega', 88: 'Xi', 89: 'Psi', 90: 'Zeta', 91: 'bracketleft', 92: 'therefore', 93: 'bracketright', 94: 'perpendicular', 95: 'underscore', 96: 'radicalex', 97: 'alpha', 98: 'beta', 99: 'chi', 100: 'delta', 101: 'epsilon', 102: 'phi', 103: 'gamma', 104: 'eta', 105: 'iota', 106: 'phi1', 107: 'kappa', 108: 'lambda', 109: 'mu', 110: 'nu', 111: 'omicron', 112: 'pi', 113: 'theta', 114: 'rho', 115: 'sigma', 116: 'tau', 117: 'upsilon', 118: 'omega1', 119: 'omega', 120: 'xi', 121: 'psi', 122: 'zeta', 123: 'braceleft', 124: 'bar', 125: 'braceright', 126: 'similar', 160: 'Euro', 161: 'Upsilon1', 162: 'minute', 163: 'lessequal', 164: 'fraction', 165: 'infinity', 166: 'florin', 167: 'club', 168: 'diamond', 169: 'heart', 170: 'spade', 171: ' arrowboth', 172: 'arrowleft', 173: 'arrowup', 174: 'arrowright', 175: 'arrowdown', 176: 'degree', 177: 'plusminus', 178: 'second', 179: 'greaterequal', 180: 'multiply', 181: 'proportional', 182: 'partialdiff', 183: 'bullet', 184: 'divide', 185: 'notequal', 186: 'equivalence', 187: 'approxequal', 188: ' ellipsis', 189: 'arrowvertex', 190: ' arrowhorizex', 191: 'carriagereturn', 192: 'aleph', 193: 'Ifraktur', 194: 'Rfraktur', 195: 'weierstrass', 196: 'circlemultiply', 197: 'circleplus', 198: 'emptyset', 199: 'intersection', 200: 'union', 201: 'propersuperset', 202: 'reflexsuperset', 203: 'notsubset', 204: 'propersubset', 205: 'reflexsubset', 206: 'element', 207: 'notelement', 208: 'angle', 209: 'gradient', 210: 'registerserif', 211: 'copyrightserif', 212: 'trademarkserif', 213: 'product', 214: 'radical', 215: 'dotmath', 216: 'logicalnot', 217: 'logicaland', 218: 'logicalor', 219: ' arrowdblboth', 220: 'arrowdblleft', 221: 'arrowdblup', 222: 'arrowdblright', 223: 'arrowdbldown', 224: 'lozenge', 225: 'angleleft', 226: 'registersans', 227: 'copyrightsans', 228: 'trademarksans', 229: 'summation', 230: 'parenlefttp', 231: 'parenleftex', 232: 'parenleftbt', 233: 'bracketlefttp', 234: 'bracketleftex', 235: 'bracketleftbt', 236: 'bracelefttp', 237: 'braceleftmid', 238: 'braceleftbt', 239: 'braceex', 241: 'angleright', 242: 'integral', 243: 'integraltp', 244: 'integralex', 245: 'integralbt', 246: 'parenrighttp', 247: 'parenrightex', 248: 'parenrightbt', 249: 'bracketrighttp', 250: 'bracketrightex', 251: 'bracketrightbt', 252: 'bracerighttp', 253: 'bracerightmid', 254: 'bracerightbt', -1: 'apple'}
ZAPFDINGBATS_BUILTIN_ENCODING = {32: 'space', 33: 'a1', 34: 'a2', 35: 'a202', 36: 'a3', 37: 'a4', 38: 'a5', 39: 'a119', 40: 'a118', 41: 'a117', 42: 'a11', 43: 'a12', 44: 'a13', 45: 'a14', 46: 'a15', 47: 'a16', 48: 'a105', 49: 'a17', 50: 'a18', 51: 'a19', 52: 'a20', 53: 'a21', 54: 'a22', 55: 'a23', 56: 'a24', 57: 'a25', 58: 'a26', 59: 'a27', 60: 'a28', 61: 'a6', 62: 'a7', 63: 'a8', 64: 'a9', 65: 'a10', 66: 'a29', 67: 'a30', 68: 'a31', 69: 'a32', 70: 'a33', 71: 'a34', 72: 'a35', 73: 'a36', 74: 'a37', 75: 'a38', 76: 'a39', 77: 'a40', 78: 'a41', 79: 'a42', 80: 'a43', 81: 'a44', 82: 'a45', 83: 'a46', 84: 'a47', 85: 'a48', 86: 'a49', 87: 'a50', 88: 'a51', 89: 'a52', 90: 'a53', 91: 'a54', 92: 'a55', 93: 'a56', 94: 'a57', 95: 'a58', 96: 'a59', 97: 'a60', 98: 'a61', 99: 'a62', 100: 'a63', 101: 'a64', 102: 'a65', 103: 'a66', 104: 'a67', 105: 'a68', 106: 'a69', 107: 'a70', 108: 'a71', 109: 'a72', 110: 'a73', 111: 'a74', 112: 'a203', 113: 'a75', 114: 'a204', 115: 'a76', 116: 'a77', 117: 'a78', 118: 'a79', 119: 'a81', 120: 'a82', 121: 'a83', 122: 'a84', 123: 'a97', 124: 'a98', 125: 'a99', 126: 'a100', 128: 'a89', 129: 'a90', 130: 'a93', 131: 'a94', 132: 'a91', 133: 'a92', 134: 'a205', 135: 'a85', 136: 'a206', 137: 'a86', 138: 'a87', 139: 'a88', 140: 'a95', 141: 'a96', 161: 'a101', 162: 'a102', 163: 'a103', 164: 'a104', 165: 'a106', 166: 'a107', 167: 'a108', 168: 'a112', 169: 'a111', 170: 'a110', 171: 'a109', 172: 'a120', 173: 'a121', 174: 'a122', 175: 'a123', 176: 'a124', 177: 'a125', 178: 'a126', 179: 'a127', 180: 'a128', 181: 'a129', 182: 'a130', 183: 'a131', 184: 'a132', 185: 'a133', 186: 'a134', 187: 'a135', 188: 'a136', 189: 'a137', 190: 'a138', 191: 'a139', 192: 'a140', 193: 'a141', 194: 'a142', 195: 'a143', 196: 'a144', 197: 'a145', 198: 'a146', 199: 'a147', 200: 'a148', 201: 'a149', 202: 'a150', 203: 'a151', 204: 'a152', 205: 'a153', 206: 'a154', 207: 'a155', 208: 'a156', 209: 'a157', 210: 'a158', 211: 'a159', 212: 'a160', 213: 'a161', 214: 'a163', 215: 'a164', 216: 'a196', 217: 'a165', 218: 'a192', 219: 'a166', 220: 'a167', 221: 'a168', 222: 'a169', 223: 'a170', 224: 'a171', 225: 'a172', 226: 'a173', 227: 'a162', 228: 'a174', 229: 'a175', 230: 'a176', 231: 'a177', 232: 'a178', 233: 'a179', 234: 'a193', 235: 'a180', 236: 'a199', 237: 'a181', 238: 'a200', 239: 'a182', 241: 'a201', 242: 'a183', 243: 'a184', 244: 'a197', 245: 'a185', 246: 'a194', 247: 'a198', 248: 'a186', 249: 'a195', 250: 'a187', 251: 'a188', 252: 'a189', 253: 'a190', 254: 'a191'}

class EncodingDB:
    encodings = {
        "StandardEncoding": STANDARD_ENCODING,
        "MacRomanEncoding": MAC_ROMAN_ENCODING,
        "WinAnsiEncoding": WIN_ANSI_ENCODING,
        "MacExpertEncoding": MAC_EXPERT_ENCODING,
    }

    @classmethod
    def get_encoding(
        cls,
        base: Union[PSLiteral, Dict[int, str]],
        diff: Optional[Iterable[object]] = None,
    ) -> Dict[int, str]:
        if isinstance(base, PSLiteral):
            encoding = cls.encodings.get(base.name, {})
        else:
            encoding = base
        if diff:
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
