import logging
import struct
from collections import deque
from io import BytesIO
from typing import BinaryIO, Deque, Dict, List, Iterator, Tuple, Union

from playa.cmapdb import ToUnicodeMap
from playa.parser import Lexer, Token, KWD, PSLiteral
from playa.utils import nunpack

log = logging.getLogger(__name__)


class CFFFontProgram:
    NIBBLES = (
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        ".",
        "e",
        "e-",
        None,
        "-",
    )

    STANDARD_STRINGS = (
        ".notdef",
        "space",
        "exclam",
        "quotedbl",
        "numbersign",
        "dollar",
        "percent",
        "ampersand",
        "quoteright",
        "parenleft",
        "parenright",
        "asterisk",
        "plus",
        "comma",
        "hyphen",
        "period",
        "slash",
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "colon",
        "semicolon",
        "less",
        "equal",
        "greater",
        "question",
        "at",
        "A",
        "B",
        "C",
        "D",
        "E",
        "F",
        "G",
        "H",
        "I",
        "J",
        "K",
        "L",
        "M",
        "N",
        "O",
        "P",
        "Q",
        "R",
        "S",
        "T",
        "U",
        "V",
        "W",
        "X",
        "Y",
        "Z",
        "bracketleft",
        "backslash",
        "bracketright",
        "asciicircum",
        "underscore",
        "quoteleft",
        "a",
        "b",
        "c",
        "d",
        "e",
        "f",
        "g",
        "h",
        "i",
        "j",
        "k",
        "l",
        "m",
        "n",
        "o",
        "p",
        "q",
        "r",
        "s",
        "t",
        "u",
        "v",
        "w",
        "x",
        "y",
        "z",
        "braceleft",
        "bar",
        "braceright",
        "asciitilde",
        "exclamdown",
        "cent",
        "sterling",
        "fraction",
        "yen",
        "florin",
        "section",
        "currency",
        "quotesingle",
        "quotedblleft",
        "guillemotleft",
        "guilsinglleft",
        "guilsinglright",
        "fi",
        "fl",
        "endash",
        "dagger",
        "daggerdbl",
        "periodcentered",
        "paragraph",
        "bullet",
        "quotesinglbase",
        "quotedblbase",
        "quotedblright",
        "guillemotright",
        "ellipsis",
        "perthousand",
        "questiondown",
        "grave",
        "acute",
        "circumflex",
        "tilde",
        "macron",
        "breve",
        "dotaccent",
        "dieresis",
        "ring",
        "cedilla",
        "hungarumlaut",
        "ogonek",
        "caron",
        "emdash",
        "AE",
        "ordfeminine",
        "Lslash",
        "Oslash",
        "OE",
        "ordmasculine",
        "ae",
        "dotlessi",
        "lslash",
        "oslash",
        "oe",
        "germandbls",
        "onesuperior",
        "logicalnot",
        "mu",
        "trademark",
        "Eth",
        "onehalf",
        "plusminus",
        "Thorn",
        "onequarter",
        "divide",
        "brokenbar",
        "degree",
        "thorn",
        "threequarters",
        "twosuperior",
        "registered",
        "minus",
        "eth",
        "multiply",
        "threesuperior",
        "copyright",
        "Aacute",
        "Acircumflex",
        "Adieresis",
        "Agrave",
        "Aring",
        "Atilde",
        "Ccedilla",
        "Eacute",
        "Ecircumflex",
        "Edieresis",
        "Egrave",
        "Iacute",
        "Icircumflex",
        "Idieresis",
        "Igrave",
        "Ntilde",
        "Oacute",
        "Ocircumflex",
        "Odieresis",
        "Ograve",
        "Otilde",
        "Scaron",
        "Uacute",
        "Ucircumflex",
        "Udieresis",
        "Ugrave",
        "Yacute",
        "Ydieresis",
        "Zcaron",
        "aacute",
        "acircumflex",
        "adieresis",
        "agrave",
        "aring",
        "atilde",
        "ccedilla",
        "eacute",
        "ecircumflex",
        "edieresis",
        "egrave",
        "iacute",
        "icircumflex",
        "idieresis",
        "igrave",
        "ntilde",
        "oacute",
        "ocircumflex",
        "odieresis",
        "ograve",
        "otilde",
        "scaron",
        "uacute",
        "ucircumflex",
        "udieresis",
        "ugrave",
        "yacute",
        "ydieresis",
        "zcaron",
        "exclamsmall",
        "Hungarumlautsmall",
        "dollaroldstyle",
        "dollarsuperior",
        "ampersandsmall",
        "Acutesmall",
        "parenleftsuperior",
        "parenrightsuperior",
        "twodotenleader",
        "onedotenleader",
        "zerooldstyle",
        "oneoldstyle",
        "twooldstyle",
        "threeoldstyle",
        "fouroldstyle",
        "fiveoldstyle",
        "sixoldstyle",
        "sevenoldstyle",
        "eightoldstyle",
        "nineoldstyle",
        "commasuperior",
        "threequartersemdash",
        "periodsuperior",
        "questionsmall",
        "asuperior",
        "bsuperior",
        "centsuperior",
        "dsuperior",
        "esuperior",
        "isuperior",
        "lsuperior",
        "msuperior",
        "nsuperior",
        "osuperior",
        "rsuperior",
        "ssuperior",
        "tsuperior",
        "ff",
        "ffi",
        "ffl",
        "parenleftinferior",
        "parenrightinferior",
        "Circumflexsmall",
        "hyphensuperior",
        "Gravesmall",
        "Asmall",
        "Bsmall",
        "Csmall",
        "Dsmall",
        "Esmall",
        "Fsmall",
        "Gsmall",
        "Hsmall",
        "Ismall",
        "Jsmall",
        "Ksmall",
        "Lsmall",
        "Msmall",
        "Nsmall",
        "Osmall",
        "Psmall",
        "Qsmall",
        "Rsmall",
        "Ssmall",
        "Tsmall",
        "Usmall",
        "Vsmall",
        "Wsmall",
        "Xsmall",
        "Ysmall",
        "Zsmall",
        "colonmonetary",
        "onefitted",
        "rupiah",
        "Tildesmall",
        "exclamdownsmall",
        "centoldstyle",
        "Lslashsmall",
        "Scaronsmall",
        "Zcaronsmall",
        "Dieresissmall",
        "Brevesmall",
        "Caronsmall",
        "Dotaccentsmall",
        "Macronsmall",
        "figuredash",
        "hypheninferior",
        "Ogoneksmall",
        "Ringsmall",
        "Cedillasmall",
        "questiondownsmall",
        "oneeighth",
        "threeeighths",
        "fiveeighths",
        "seveneighths",
        "onethird",
        "twothirds",
        "zerosuperior",
        "foursuperior",
        "fivesuperior",
        "sixsuperior",
        "sevensuperior",
        "eightsuperior",
        "ninesuperior",
        "zeroinferior",
        "oneinferior",
        "twoinferior",
        "threeinferior",
        "fourinferior",
        "fiveinferior",
        "sixinferior",
        "seveninferior",
        "eightinferior",
        "nineinferior",
        "centinferior",
        "dollarinferior",
        "periodinferior",
        "commainferior",
        "Agravesmall",
        "Aacutesmall",
        "Acircumflexsmall",
        "Atildesmall",
        "Adieresissmall",
        "Aringsmall",
        "AEsmall",
        "Ccedillasmall",
        "Egravesmall",
        "Eacutesmall",
        "Ecircumflexsmall",
        "Edieresissmall",
        "Igravesmall",
        "Iacutesmall",
        "Icircumflexsmall",
        "Idieresissmall",
        "Ethsmall",
        "Ntildesmall",
        "Ogravesmall",
        "Oacutesmall",
        "Ocircumflexsmall",
        "Otildesmall",
        "Odieresissmall",
        "OEsmall",
        "Oslashsmall",
        "Ugravesmall",
        "Uacutesmall",
        "Ucircumflexsmall",
        "Udieresissmall",
        "Yacutesmall",
        "Thornsmall",
        "Ydieresissmall",
        "001.000",
        "001.001",
        "001.002",
        "001.003",
        "Black",
        "Bold",
        "Book",
        "Light",
        "Medium",
        "Regular",
        "Roman",
        "Semibold",
    )

    STANDARD_ENCODING = (
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
        37,
        38,
        39,
        40,
        41,
        42,
        43,
        44,
        45,
        46,
        47,
        48,
        49,
        50,
        51,
        52,
        53,
        54,
        55,
        56,
        57,
        58,
        59,
        60,
        61,
        62,
        63,
        64,
        65,
        66,
        67,
        68,
        69,
        70,
        71,
        72,
        73,
        74,
        75,
        76,
        77,
        78,
        79,
        80,
        81,
        82,
        83,
        84,
        85,
        86,
        87,
        88,
        89,
        90,
        91,
        92,
        93,
        94,
        95,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        96,
        97,
        98,
        99,
        100,
        101,
        102,
        103,
        104,
        105,
        106,
        107,
        108,
        109,
        110,
        0,
        111,
        112,
        113,
        114,
        0,
        115,
        116,
        117,
        118,
        119,
        120,
        121,
        122,
        0,
        123,
        0,
        124,
        125,
        126,
        127,
        128,
        129,
        130,
        131,
        0,
        132,
        133,
        0,
        134,
        135,
        136,
        137,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        138,
        0,
        139,
        0,
        0,
        0,
        0,
        140,
        141,
        142,
        143,
        0,
        0,
        0,
        0,
        0,
        144,
        0,
        0,
        0,
        145,
        0,
        0,
        146,
        147,
        148,
        149,
        0,
        0,
        0,
        0,
    )
    EXPERT_ENCODING = (
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        229,
        230,
        0,
        231,
        232,
        233,
        234,
        235,
        236,
        237,
        238,
        13,
        14,
        15,
        99,
        239,
        240,
        241,
        242,
        243,
        244,
        245,
        246,
        247,
        248,
        27,
        28,
        249,
        250,
        251,
        252,
        0,
        253,
        254,
        255,
        256,
        257,
        0,
        0,
        0,
        258,
        0,
        0,
        259,
        260,
        261,
        262,
        0,
        0,
        263,
        264,
        265,
        0,
        266,
        109,
        110,
        267,
        268,
        269,
        0,
        270,
        271,
        272,
        273,
        274,
        275,
        276,
        277,
        278,
        279,
        280,
        281,
        282,
        283,
        284,
        285,
        286,
        287,
        288,
        289,
        290,
        291,
        292,
        293,
        294,
        295,
        296,
        297,
        298,
        299,
        300,
        301,
        302,
        303,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        304,
        305,
        306,
        0,
        0,
        307,
        308,
        309,
        310,
        311,
        0,
        312,
        0,
        0,
        313,
        0,
        0,
        314,
        315,
        0,
        0,
        316,
        317,
        318,
        0,
        0,
        0,
        158,
        155,
        163,
        319,
        320,
        321,
        322,
        323,
        324,
        325,
        0,
        0,
        326,
        150,
        164,
        169,
        327,
        328,
        329,
        330,
        331,
        332,
        333,
        334,
        335,
        336,
        337,
        338,
        339,
        340,
        341,
        342,
        343,
        344,
        345,
        346,
        347,
        348,
        349,
        350,
        351,
        352,
        353,
        354,
        355,
        356,
        357,
        358,
        359,
        360,
        361,
        362,
        363,
        364,
        365,
        366,
        367,
        368,
        369,
        370,
        371,
        372,
        373,
        374,
        375,
        376,
        377,
        378,
    )
    PREDEFINED_ENCODINGS = (STANDARD_ENCODING, EXPERT_ENCODING)

    ISOADOBE_CHARSET = (
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
        37,
        38,
        39,
        40,
        41,
        42,
        43,
        44,
        45,
        46,
        47,
        48,
        49,
        50,
        51,
        52,
        53,
        54,
        55,
        56,
        57,
        58,
        59,
        60,
        61,
        62,
        63,
        64,
        65,
        66,
        67,
        68,
        69,
        70,
        71,
        72,
        73,
        74,
        75,
        76,
        77,
        78,
        79,
        80,
        81,
        82,
        83,
        84,
        85,
        86,
        87,
        88,
        89,
        90,
        91,
        92,
        93,
        94,
        95,
        96,
        97,
        98,
        99,
        100,
        101,
        102,
        103,
        104,
        105,
        106,
        107,
        108,
        109,
        110,
        111,
        112,
        113,
        114,
        115,
        116,
        117,
        118,
        119,
        120,
        121,
        122,
        123,
        124,
        125,
        126,
        127,
        128,
        129,
        130,
        131,
        132,
        133,
        134,
        135,
        136,
        137,
        138,
        139,
        140,
        141,
        142,
        143,
        144,
        145,
        146,
        147,
        148,
        149,
        150,
        151,
        152,
        153,
        154,
        155,
        156,
        157,
        158,
        159,
        160,
        161,
        162,
        163,
        164,
        165,
        166,
        167,
        168,
        169,
        170,
        171,
        172,
        173,
        174,
        175,
        176,
        177,
        178,
        179,
        180,
        181,
        182,
        183,
        184,
        185,
        186,
        187,
        188,
        189,
        190,
        191,
        192,
        193,
        194,
        195,
        196,
        197,
        198,
        199,
        200,
        201,
        202,
        203,
        204,
        205,
        206,
        207,
        208,
        209,
        210,
        211,
        212,
        213,
        214,
        215,
        216,
        217,
        218,
        219,
        220,
        221,
        222,
        223,
        224,
        225,
        226,
        227,
        228,
    )
    EXPERT_CHARSET = (
        1,
        229,
        230,
        231,
        232,
        233,
        234,
        235,
        236,
        237,
        238,
        13,
        14,
        15,
        99,
        239,
        240,
        241,
        242,
        243,
        244,
        245,
        246,
        247,
        248,
        27,
        28,
        249,
        250,
        251,
        252,
        253,
        254,
        255,
        256,
        257,
        258,
        259,
        260,
        261,
        262,
        263,
        264,
        265,
        266,
        109,
        110,
        267,
        268,
        269,
        270,
        271,
        272,
        273,
        274,
        275,
        276,
        277,
        278,
        279,
        280,
        281,
        282,
        283,
        284,
        285,
        286,
        287,
        288,
        289,
        290,
        291,
        292,
        293,
        294,
        295,
        296,
        297,
        298,
        299,
        300,
        301,
        302,
        303,
        304,
        305,
        306,
        307,
        308,
        309,
        310,
        311,
        312,
        313,
        314,
        315,
        316,
        317,
        318,
        158,
        155,
        163,
        319,
        320,
        321,
        322,
        323,
        324,
        325,
        326,
        150,
        164,
        169,
        327,
        328,
        329,
        330,
        331,
        332,
        333,
        334,
        335,
        336,
        337,
        338,
        339,
        340,
        341,
        342,
        343,
        344,
        345,
        346,
        347,
        348,
        349,
        350,
        351,
        352,
        353,
        354,
        355,
        356,
        357,
        358,
        359,
        360,
        361,
        362,
        363,
        364,
        365,
        366,
        367,
        368,
        369,
        370,
        371,
        372,
        373,
        374,
        375,
        376,
        377,
        378,
    )
    EXPERT_SUBSET_CHARSET = (
        1,
        231,
        232,
        235,
        236,
        237,
        238,
        13,
        14,
        15,
        99,
        239,
        240,
        241,
        242,
        243,
        244,
        245,
        246,
        247,
        248,
        27,
        28,
        249,
        250,
        251,
        253,
        254,
        255,
        256,
        257,
        258,
        259,
        260,
        261,
        262,
        263,
        264,
        265,
        266,
        109,
        110,
        267,
        268,
        269,
        270,
        272,
        300,
        301,
        302,
        305,
        314,
        315,
        158,
        155,
        163,
        320,
        321,
        322,
        323,
        324,
        325,
        326,
        150,
        164,
        169,
        327,
        328,
        329,
        330,
        331,
        332,
        333,
        334,
        335,
        336,
        337,
        338,
        339,
        340,
        341,
        342,
        343,
        344,
        345,
        346,
    )
    PREDEFINED_CHARSETS = (ISOADOBE_CHARSET, EXPERT_CHARSET, EXPERT_SUBSET_CHARSET)

    class INDEX:
        def __init__(self, fp: BinaryIO) -> None:
            self.fp = fp
            self.offsets: List[int] = []
            (count,) = struct.unpack(">H", self.fp.read(2))
            if count == 0:
                return
            (offsize,) = struct.unpack("B", self.fp.read(1))
            for i in range(count + 1):
                self.offsets.append(nunpack(self.fp.read(offsize)))
            self.base = self.fp.tell() - 1
            self.fp.seek(self.base + self.offsets[-1])

        def __repr__(self) -> str:
            return "<INDEX: size=%d>" % len(self)

        def __len__(self) -> int:
            return len(self.offsets) - 1

        def __getitem__(self, i: int) -> bytes:
            self.fp.seek(self.base + self.offsets[i])
            return self.fp.read(self.offsets[i + 1] - self.offsets[i])

        def __iter__(self) -> Iterator[bytes]:
            return iter(self[i] for i in range(len(self)))

    def __init__(self, name: str, fp: BinaryIO) -> None:
        self.name = name
        self.fp = fp
        # Header
        (_major, _minor, hdrsize, offsize) = struct.unpack("BBBB", self.fp.read(4))
        self.fp.read(hdrsize - 4)
        # Name INDEX
        self.name_index = self.INDEX(self.fp)
        # Top DICT INDEX
        self.dict_index = self.INDEX(self.fp)
        # String INDEX
        self.string_index = self.INDEX(self.fp)
        # Global Subr INDEX
        self.subr_index = self.INDEX(self.fp)
        # Top DICT DATA
        self.top_dict = self.getdict(self.dict_index[0])
        self.is_cidfont = (12, 30) in self.top_dict
        (charset_pos,) = self.top_dict.get(15, [0])
        (encoding_pos,) = self.top_dict.get(16, [0])
        (charstring_pos,) = self.top_dict.get(17, [0])
        # CharStrings
        self.fp.seek(int(charstring_pos))
        self.charstring = self.INDEX(self.fp)
        self.nglyphs = len(self.charstring)
        self._parse_charset(int(charset_pos))
        if not self.is_cidfont:
            self.name2gid = {self.getstr(sid): gid for gid, sid in self.gid2sid.items()}
            self._parse_encoding(int(encoding_pos))
            self.code2name = {
                code: self.getstr(self.gid2sid[gid])
                for code, gid in self.code2gid.items()
                if gid in self.gid2sid
            }
        else:
            self.cid2gid = {sid: gid for gid, sid in self.gid2sid.items()}

    def _parse_encoding(self, encoding_pos: int) -> None:
        # Encodings
        self.code2gid = {}
        if encoding_pos in (0, 1):
            for code, sid in enumerate(self.PREDEFINED_ENCODINGS[encoding_pos]):
                if gid := self.name2gid.get(self.getstr(sid)):
                    self.code2gid[code] = gid
            return
        self.fp.seek(encoding_pos)
        (format,) = self.fp.read(1)
        supp, format = format & 0x80, format & 0x7F
        self.encoding_format = format
        if format == 0:
            # Format 0
            (n,) = struct.unpack("B", self.fp.read(1))
            for gid, code in enumerate(
                struct.unpack("B" * n, self.fp.read(n)), start=1
            ):
                self.code2gid[code] = gid
        elif format == 1:
            # Format 1
            (n,) = struct.unpack("B", self.fp.read(1))
            gid = 1
            for i in range(n):
                (first, nleft) = struct.unpack("BB", self.fp.read(2))
                for code in range(first, first + nleft + 1):
                    self.code2gid[code] = gid
                    gid += 1
        else:
            raise ValueError("unsupported encoding format: %r" % format)
        if supp:
            (n,) = struct.unpack("B", self.fp.read(1))
            for i in range(n):
                code, sid = struct.unpack(">BH", self.fp.read(3))
                if gid := self.name2gid.get(self.getstr(sid)):
                    self.code2gid[code] = gid

    def _parse_charset(self, charset_pos: int) -> None:
        # Charsets
        self.gid2sid = {}
        if charset_pos in (0, 1, 2):
            if self.is_cidfont:
                raise ValueError("no predefined charsets for CID CFF fonts")
            for gid, sid in enumerate(self.PREDEFINED_CHARSETS[charset_pos], start=1):
                self.gid2sid[gid] = sid
            return
        self.fp.seek(charset_pos)
        (format,) = self.fp.read(1)
        self.charset_format = format
        if format == 0:
            # Format 0
            n = self.nglyphs - 1
            for gid, sid in enumerate(
                struct.unpack(">" + "H" * n, self.fp.read(2 * n)), start=1
            ):
                self.gid2sid[gid] = sid
        elif format in (1, 2):
            # Format 1 & 2
            range_f = ">HB" if format == 1 else ">HH"
            range_f_size = struct.calcsize(range_f)
            gid = 1
            while gid < self.nglyphs:
                (first, nleft) = struct.unpack(range_f, self.fp.read(range_f_size))
                for sid in range(first, first + nleft + 1):
                    self.gid2sid[gid] = sid
                    gid += 1
        else:
            raise ValueError("unsupported charset format: %r" % format)

    def getstr(self, sid: int) -> str:
        if sid < len(self.STANDARD_STRINGS):
            return self.STANDARD_STRINGS[sid]
        return self.string_index[sid - len(self.STANDARD_STRINGS)].decode("ascii")

    def getdict(
        self, data: bytes
    ) -> Dict[Union[Tuple[int, int], int], List[Union[float, int]]]:
        d: Dict[Union[Tuple[int, int], int], List[Union[float, int]]] = {}
        fp = BytesIO(data)
        stack: List[Union[float, int]] = []
        while 1:
            c = fp.read(1)
            if not c:
                break
            b0 = ord(c)
            if b0 <= 21:
                key = (12, ord(fp.read(1))) if b0 == 12 else b0
                d[key] = stack
                stack = []
                continue
            if b0 == 30:
                s = ""
                loop = True
                while loop:
                    b = ord(fp.read(1))
                    for n in (b >> 4, b & 15):
                        if n == 15:
                            loop = False
                        else:
                            nibble = self.NIBBLES[n]
                            assert nibble is not None
                            s += nibble
                value = float(s)
            elif b0 >= 32 and b0 <= 246:
                value = b0 - 139
            else:
                b1 = ord(fp.read(1))
                if b0 >= 247 and b0 <= 250:
                    value = ((b0 - 247) << 8) + b1 + 108
                elif b0 >= 251 and b0 <= 254:
                    value = -((b0 - 251) << 8) - b1 - 108
                else:
                    b2 = ord(fp.read(1))
                    if b1 >= 128:
                        b1 -= 256
                    if b0 == 28:
                        value = b1 << 8 | b2
                    else:
                        value = b1 << 24 | b2 << 16 | struct.unpack(">H", fp.read(2))[0]
            stack.append(value)
        return d


class TrueTypeFontProgram:
    """Read TrueType font programs to get Unicode mappings."""

    def __init__(self, name: str, fp: BinaryIO) -> None:
        self.name = name
        self.fp = fp
        self.tables: Dict[bytes, Tuple[int, int]] = {}
        self.fonttype = fp.read(4)
        try:
            (ntables, _1, _2, _3) = struct.unpack(">HHHH", fp.read(8))
            for _ in range(ntables):
                (name_bytes, tsum, offset, length) = struct.unpack(
                    ">4sLLL", fp.read(16)
                )
                self.tables[name_bytes] = (offset, length)
        except struct.error:
            # Do not fail if there are not enough bytes to read. Even for
            # corrupted PDFs we would like to get as much information as
            # possible, so continue.
            pass

    def create_tounicode(self) -> Union[ToUnicodeMap, None]:
        """Recreate a ToUnicode mapping from a TrueType font program."""
        if b"cmap" not in self.tables:
            log.debug("TrueType font program has no character mapping")
            return None
        (base_offset, length) = self.tables[b"cmap"]
        fp = self.fp
        fp.seek(base_offset)
        (version, nsubtables) = struct.unpack(">HH", fp.read(4))
        subtables: List[Tuple[int, int, int]] = []
        for i in range(nsubtables):
            subtables.append(struct.unpack(">HHL", fp.read(8)))
        char2gid: Dict[int, int] = {}
        # Only supports subtable type 0, 2 and 4.
        for platform_id, encoding_id, st_offset in subtables:
            # Skip non-Unicode cmaps.
            # https://docs.microsoft.com/en-us/typography/opentype/spec/cmap
            if not (platform_id == 0 or (platform_id == 3 and encoding_id in [1, 10])):
                continue
            fp.seek(base_offset + st_offset)
            (fmttype, fmtlen, fmtlang) = struct.unpack(">HHH", fp.read(6))
            if fmttype == 0:
                char2gid.update(enumerate(struct.unpack(">256B", fp.read(256))))
            elif fmttype == 2:
                subheaderkeys = struct.unpack(">256H", fp.read(512))
                firstbytes = [0] * 8192
                for i, k in enumerate(subheaderkeys):
                    firstbytes[k // 8] = i
                nhdrs = max(subheaderkeys) // 8 + 1
                hdrs: List[Tuple[int, int, int, int, int]] = []
                for i in range(nhdrs):
                    (firstcode, entcount, delta, offset) = struct.unpack(
                        ">HHhH", fp.read(8)
                    )
                    hdrs.append((i, firstcode, entcount, delta, fp.tell() - 2 + offset))
                for i, firstcode, entcount, delta, pos in hdrs:
                    if not entcount:
                        continue
                    first = firstcode + (firstbytes[i] << 8)
                    fp.seek(pos)
                    for c in range(entcount):
                        gid = struct.unpack(">H", fp.read(2))[0]
                        if gid:
                            gid += delta
                        char2gid[first + c] = gid
            elif fmttype == 4:
                (segcount, _1, _2, _3) = struct.unpack(">HHHH", fp.read(8))
                segcount //= 2
                ecs = struct.unpack(">%dH" % segcount, fp.read(2 * segcount))
                fp.read(2)
                scs = struct.unpack(">%dH" % segcount, fp.read(2 * segcount))
                idds = struct.unpack(">%dh" % segcount, fp.read(2 * segcount))
                pos = fp.tell()
                idrs = struct.unpack(">%dH" % segcount, fp.read(2 * segcount))
                for ec, sc, idd, idr in zip(ecs, scs, idds, idrs):
                    if idr:
                        fp.seek(pos + idr)
                        for c in range(sc, ec + 1):
                            b = struct.unpack(">H", fp.read(2))[0]
                            char2gid[c] = (b + idd) & 0xFFFF
                    else:
                        for c in range(sc, ec + 1):
                            char2gid[c] = (c + idd) & 0xFFFF
            else:
                # FIXME: support at least format 12 for non-BMP chars
                # (probably rare in real life since there should be a
                # ToUnicode mapping already)
                assert False, str(("Unhandled", fmttype))
        if not char2gid:
            log.debug("unicode mapping is empty")
            return None
        # Create unicode map - as noted above we don't yet support
        # Unicode outside the BMP, so this is 16-bit only.
        tounicode = ToUnicodeMap()
        tounicode.add_code_range(b"\x00\x00", b"\xff\xff")
        for char, gid in char2gid.items():
            tounicode.add_code2code(gid, char, 2)
        return tounicode


KEYWORD_BEGIN = KWD(b"begin")
KEYWORD_END = KWD(b"end")
KEYWORD_DEF = KWD(b"def")
KEYWORD_PUT = KWD(b"put")
KEYWORD_DICT = KWD(b"dict")
KEYWORD_ARRAY = KWD(b"array")
KEYWORD_READONLY = KWD(b"readonly")
KEYWORD_FOR = KWD(b"for")


class Type1FontHeaderParser:
    def __init__(self, data: bytes) -> None:
        self._lexer = Lexer(data)
        self._encoding: Dict[int, str] = {}
        self._tokq: Deque[Token] = deque([], 2)

    def get_encoding(self) -> Dict[int, str]:
        """Parse the font encoding.

        The Type1 font encoding maps character codes to character names. These
        character names could either be standard Adobe glyph names, or
        character names associated with custom CharStrings for this font. A
        CharString is a sequence of operations that describe how the character
        should be drawn. Currently, this function returns '' (empty string)
        for character names that are associated with a CharStrings.

        Reference: Adobe Systems Incorporated, Adobe Type 1 Font Format

        :returns mapping of character identifiers (cid's) to unicode characters
        """
        for _, tok in self._lexer:
            # Ignore anything that isn't INT NAME put
            if tok is KEYWORD_PUT:
                cid, name = self._tokq
                if isinstance(cid, int) and isinstance(name, PSLiteral):
                    self._encoding[cid] = name.name
            else:
                self._tokq.append(tok)
        return self._encoding
