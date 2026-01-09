# CCITT Fax decoder
#
# Bugs: uncompressed mode untested.
#
# cf.
#  ITU-T Recommendation T.4
#    "Standardization of Group 3 facsimile terminals
#    for document transmission"
#  ITU-T Recommendation T.6
#    "FACSIMILE CODING SCHEMES AND CODING CONTROL FUNCTIONS
#    FOR GROUP 4 FACSIMILE APPARATUS"


import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Tuple,
    Union,
)
from playa.pdftypes import PDFObject, int_value

if TYPE_CHECKING:
    from mypy_extensions import u8

LOG = logging.getLogger(__name__)
BitParserNode = Union[int, str, None, List]


class CCITTException(Exception):
    pass


class EOFB(CCITTException):
    pass


class InvalidData(CCITTException):
    pass


class ByteSkip(CCITTException):
    pass


class BitParserTree:
    def __init__(self, name: str, *tree: Tuple[Union[int, str], str]) -> None:
        self.root: BitParserNode = [None, None]
        self.name = name
        for v, bits in tree:
            self.add(v, bits)

    def add(self, v: Union[int, str], bits: str) -> None:
        p = self.root
        b = None
        for i in range(len(bits)):
            if i > 0:
                assert b is not None
                assert isinstance(p, list)
                if p[b] is None:
                    p[b] = [None, None]
                p = p[b]
            b = int(bits[i])
        assert b is not None
        assert isinstance(p, list)
        p[b] = v


MODE = BitParserTree(
    "MODE",
    (0, "1"),
    (+1, "011"),
    (-1, "010"),
    ("h", "001"),
    ("p", "0001"),
    (+2, "000011"),
    (-2, "000010"),
    (+3, "0000011"),
    (-3, "0000010"),
    ("u", "0000001111"),
    # These are all unsupported (raise InvalidData)
    ("x1", "0000001000"),
    ("x2", "0000001001"),
    ("x3", "0000001010"),
    ("x4", "0000001011"),
    ("x5", "0000001100"),
    ("x6", "0000001101"),
    ("x7", "0000001110"),
    ("e", "000000000001"),
)

NEXT2D = BitParserTree("NEXT2D", (0, "1"), (1, "0"))

WHITE = BitParserTree(
    "WHITE",
    (0, "00110101"),
    (1, "000111"),
    (2, "0111"),
    (3, "1000"),
    (4, "1011"),
    (5, "1100"),
    (6, "1110"),
    (7, "1111"),
    (8, "10011"),
    (9, "10100"),
    (10, "00111"),
    (11, "01000"),
    (12, "001000"),
    (13, "000011"),
    (14, "110100"),
    (15, "110101"),
    (16, "101010"),
    (17, "101011"),
    (18, "0100111"),
    (19, "0001100"),
    (20, "0001000"),
    (21, "0010111"),
    (22, "0000011"),
    (23, "0000100"),
    (24, "0101000"),
    (25, "0101011"),
    (26, "0010011"),
    (27, "0100100"),
    (28, "0011000"),
    (29, "00000010"),
    (30, "00000011"),
    (31, "00011010"),
    (32, "00011011"),
    (33, "00010010"),
    (34, "00010011"),
    (35, "00010100"),
    (36, "00010101"),
    (37, "00010110"),
    (38, "00010111"),
    (39, "00101000"),
    (40, "00101001"),
    (41, "00101010"),
    (42, "00101011"),
    (43, "00101100"),
    (44, "00101101"),
    (45, "00000100"),
    (46, "00000101"),
    (47, "00001010"),
    (48, "00001011"),
    (49, "01010010"),
    (50, "01010011"),
    (51, "01010100"),
    (52, "01010101"),
    (53, "00100100"),
    (54, "00100101"),
    (55, "01011000"),
    (56, "01011001"),
    (57, "01011010"),
    (58, "01011011"),
    (59, "01001010"),
    (60, "01001011"),
    (61, "00110010"),
    (62, "00110011"),
    (63, "00110100"),
    (64, "11011"),
    (128, "10010"),
    (192, "010111"),
    (256, "0110111"),
    (320, "00110110"),
    (384, "00110111"),
    (448, "01100100"),
    (512, "01100101"),
    (576, "01101000"),
    (640, "01100111"),
    (704, "011001100"),
    (768, "011001101"),
    (832, "011010010"),
    (896, "011010011"),
    (960, "011010100"),
    (1024, "011010101"),
    (1088, "011010110"),
    (1152, "011010111"),
    (1216, "011011000"),
    (1280, "011011001"),
    (1344, "011011010"),
    (1408, "011011011"),
    (1472, "010011000"),
    (1536, "010011001"),
    (1600, "010011010"),
    (1664, "011000"),
    (1728, "010011011"),
    (1792, "00000001000"),
    (1856, "00000001100"),
    (1920, "00000001101"),
    (1984, "000000010010"),
    (2048, "000000010011"),
    (2112, "000000010100"),
    (2176, "000000010101"),
    (2240, "000000010110"),
    (2304, "000000010111"),
    (2368, "000000011100"),
    (2432, "000000011101"),
    (2496, "000000011110"),
    (2560, "000000011111"),
    ("e", "000000000001"),
)

BLACK = BitParserTree(
    "BLACK",
    (0, "0000110111"),
    (1, "010"),
    (2, "11"),
    (3, "10"),
    (4, "011"),
    (5, "0011"),
    (6, "0010"),
    (7, "00011"),
    (8, "000101"),
    (9, "000100"),
    (10, "0000100"),
    (11, "0000101"),
    (12, "0000111"),
    (13, "00000100"),
    (14, "00000111"),
    (15, "000011000"),
    (16, "0000010111"),
    (17, "0000011000"),
    (18, "0000001000"),
    (19, "00001100111"),
    (20, "00001101000"),
    (21, "00001101100"),
    (22, "00000110111"),
    (23, "00000101000"),
    (24, "00000010111"),
    (25, "00000011000"),
    (26, "000011001010"),
    (27, "000011001011"),
    (28, "000011001100"),
    (29, "000011001101"),
    (30, "000001101000"),
    (31, "000001101001"),
    (32, "000001101010"),
    (33, "000001101011"),
    (34, "000011010010"),
    (35, "000011010011"),
    (36, "000011010100"),
    (37, "000011010101"),
    (38, "000011010110"),
    (39, "000011010111"),
    (40, "000001101100"),
    (41, "000001101101"),
    (42, "000011011010"),
    (43, "000011011011"),
    (44, "000001010100"),
    (45, "000001010101"),
    (46, "000001010110"),
    (47, "000001010111"),
    (48, "000001100100"),
    (49, "000001100101"),
    (50, "000001010010"),
    (51, "000001010011"),
    (52, "000000100100"),
    (53, "000000110111"),
    (54, "000000111000"),
    (55, "000000100111"),
    (56, "000000101000"),
    (57, "000001011000"),
    (58, "000001011001"),
    (59, "000000101011"),
    (60, "000000101100"),
    (61, "000001011010"),
    (62, "000001100110"),
    (63, "000001100111"),
    (64, "0000001111"),
    (128, "000011001000"),
    (192, "000011001001"),
    (256, "000001011011"),
    (320, "000000110011"),
    (384, "000000110100"),
    (448, "000000110101"),
    (512, "0000001101100"),
    (576, "0000001101101"),
    (640, "0000001001010"),
    (704, "0000001001011"),
    (768, "0000001001100"),
    (832, "0000001001101"),
    (896, "0000001110010"),
    (960, "0000001110011"),
    (1024, "0000001110100"),
    (1088, "0000001110101"),
    (1152, "0000001110110"),
    (1216, "0000001110111"),
    (1280, "0000001010010"),
    (1344, "0000001010011"),
    (1408, "0000001010100"),
    (1472, "0000001010101"),
    (1536, "0000001011010"),
    (1600, "0000001011011"),
    (1664, "0000001100100"),
    (1728, "0000001100101"),
    (1792, "00000001000"),
    (1856, "00000001100"),
    (1920, "00000001101"),
    (1984, "000000010010"),
    (2048, "000000010011"),
    (2112, "000000010100"),
    (2176, "000000010101"),
    (2240, "000000010110"),
    (2304, "000000010111"),
    (2368, "000000011100"),
    (2432, "000000011101"),
    (2496, "000000011110"),
    (2560, "000000011111"),
    ("e", "000000000001"),
)

UNCOMPRESSED = BitParserTree(
    "UNCOMPRESSED",
    ("1", "1"),
    ("01", "01"),
    ("001", "001"),
    ("0001", "0001"),
    ("00001", "00001"),
    ("00000", "000001"),
    ("T00", "00000011"),
    ("T10", "00000010"),
    ("T000", "000000011"),
    ("T100", "000000010"),
    ("T0000", "0000000011"),
    ("T1000", "0000000010"),
    ("T00000", "00000000011"),
    ("T10000", "00000000010"),
    ("e", "000000000001"),
)


class BitParser:
    _state: BitParserTree
    _node: BitParserNode
    _accept: Callable[[BitParserNode], BitParserTree]

    def __init__(self) -> None:
        self._pos = 0
        self._node = None
        self._bits: List[int] = []

    def _parse_bit(self, x: int) -> None:
        if self._node is None:
            self._node = self._state.root
        bit = not not x
        self._bits.append(bit)
        assert isinstance(self._node, list)
        v = self._node[bit]
        # LOG.debug("bits: %s v: %r", self.code_bits, v)
        self._pos += 1
        if isinstance(v, list):
            self._node = v
        else:
            assert self._accept is not None
            # LOG.debug("%s code: %s", self.state_name, self.code_bits)
            self._state = self._accept(v)
            # LOG.debug("=> %s", self.state_name)
            self._node = self._state.root
            self._bits.clear()

    @property
    def state_name(self) -> str:
        return self._state.name

    @property
    def code_bits(self) -> str:
        return "".join("1" if bit else "0" for bit in self._bits)


class CCITTG4Parser(BitParser):
    _color: int
    _curline: List["u8"]
    _refline: List["u8"]

    def __init__(self, width: int, height: int, bytealign: bool = False) -> None:
        super().__init__()
        self.width = width
        self.height = height
        self.bytealign = bytealign
        self.reset()

    def feedbytes(self, data: bytes) -> None:
        for byte in data:
            try:
                # bits = "".join(
                # "1" if (byte & m) else "0" for m in (128, 64, 32, 16, 8, 4, 2, 1)
                # )
                # LOG.debug("byte: %s", bits)
                for m in (128, 64, 32, 16, 8, 4, 2, 1):
                    self._parse_bit(byte & m)
            except ByteSkip:
                # LOG.debug("=> ByteSkip => MODE")
                self._accept = self._parse_mode
                self._state = MODE
                self._node = self._state.root
                self._bits.clear()
            except InvalidData:
                LOG.warning("Unknown %s code: %r", self.state_name, self.code_bits)
                break
            except EOFB:
                break

    def _parse_mode(self, mode: BitParserNode) -> BitParserTree:
        # Act on a code from the leaves of MODE
        if mode == "p":  # twoDimPass
            self._do_pass()
            self._flush_line()
            return MODE
        elif mode == "h":  # twoDimHoriz
            self._n1 = 0
            self._accept = self._parse_horiz1
            return WHITE if self._color else BLACK
        elif mode == "u":  # uncompressed (unsupported by pdf.js?)
            self._accept = self._parse_uncompressed
            return UNCOMPRESSED
        elif mode == "e":  # EOL, just ignore this
            return MODE
        elif isinstance(mode, str) and mode[0] == "x":
            LOG.warning("Skipping unsupported code: %s (%s)", mode, self.code_bits)
            return MODE
        elif isinstance(mode, int):  # twoDimVert[LR]\d
            self._do_vertical(mode)
            self._flush_line()
            return MODE
        else:
            raise InvalidData

    def _parse_horiz1(self, n: BitParserNode) -> BitParserTree:
        if not isinstance(n, int):
            raise InvalidData
        self._n1 += n
        if n < 64:
            self._n2 = 0
            self._color = 1 - self._color
            self._accept = self._parse_horiz2
        return WHITE if self._color else BLACK

    def _parse_horiz2(self, n: BitParserNode) -> BitParserTree:
        if not isinstance(n, int):
            raise InvalidData
        self._n2 += n
        if n < 64:
            # Set this back to what it was for _parse_horiz1, then
            # output the two stretches of white/black or black/white
            self._color = 1 - self._color
            self._accept = self._parse_mode
            self._do_horizontal(self._n1, self._n2)
            self._flush_line()
            return MODE
        return WHITE if self._color else BLACK

    def _parse_uncompressed(self, bits: BitParserNode) -> BitParserTree:
        if not isinstance(bits, str):
            raise InvalidData
        if bits.startswith("T"):
            self._accept = self._parse_mode
            self._color = int(bits[1])
            self._do_uncompressed(bits[2:])
            return MODE
        else:
            self._do_uncompressed(bits)
            return UNCOMPRESSED

    def _get_bits(self) -> str:
        return "".join(str(b) for b in self._curline[: self._curpos])

    def _get_refline(self, i: int) -> str:
        if i < 0:
            return "[]" + "".join(str(b) for b in self._refline)
        elif self.width <= i:
            return "".join(str(b) for b in self._refline) + "[]"
        else:
            return (
                "".join(str(b) for b in self._refline[:i])
                + "["
                + str(self._refline[i])
                + "]"
                + "".join(str(b) for b in self._refline[i + 1 :])
            )

    def reset(self) -> None:
        self._y = 0
        self._curline = [1] * self.width
        self._reset_line()
        self._accept = self._parse_mode
        self._state = MODE

    def output_line(self, y: int, bits: List["u8"]) -> None:
        print(y, "".join(str(b) for b in bits))

    def _reset_line(self) -> None:
        # We could just swap them, like in PNG prediction, though it's
        # not clear that would be much faster.
        self._refline = self._curline
        self._curline = [1] * self.width
        self._curpos = -1
        self._color = 1

    def _flush_line(self) -> None:
        if self.width <= self._curpos:
            self.output_line(self._y, self._curline)
            self._y += 1
            self._reset_line()
            if self.bytealign:
                raise ByteSkip

    def _do_vertical(self, dx: int) -> None:
        x1 = self._curpos + 1
        while 1:
            if x1 == 0:
                if self._color == 1 and self._refline[x1] != self._color:
                    break
            elif x1 == self.width or (
                self._refline[x1 - 1] == self._color
                and self._refline[x1] != self._color
            ):
                break
            x1 += 1
        x1 += dx
        x0 = max(0, self._curpos)
        x1 = max(0, min(self.width, x1))
        if x1 < x0:
            for x in range(x1, x0):
                self._curline[x] = self._color
        elif x0 < x1:
            for x in range(x0, x1):
                self._curline[x] = self._color
        self._curpos = x1
        self._color = 1 - self._color

    def _do_pass(self) -> None:
        x1 = self._curpos + 1
        while True:
            if x1 == 0:
                if self._color == 1 and self._refline[x1] != self._color:
                    break
            elif x1 == self.width or (
                self._refline[x1 - 1] == self._color
                and self._refline[x1] != self._color
            ):
                break
            x1 += 1
        while True:
            if x1 == 0:
                if self._color == 0 and self._refline[x1] == self._color:
                    break
            elif x1 == self.width or (
                self._refline[x1 - 1] != self._color
                and self._refline[x1] == self._color
            ):
                break
            x1 += 1
        for x in range(self._curpos, x1):
            self._curline[x] = self._color
        self._curpos = x1

    def _do_horizontal(self, n1: int, n2: int) -> None:
        if self._curpos < 0:
            self._curpos = 0
        endpos = min(self.width, self._curpos + n1)
        for idx in range(self._curpos, endpos):
            self._curline[idx] = self._color
        self._curpos = endpos
        endpos = min(self.width, self._curpos + n2)
        for idx in range(self._curpos, endpos):
            self._curline[idx] = 1 - self._color
        self._curpos = endpos

    def _do_horizontal_one(self, n: int) -> None:
        if self._curpos < 0:
            self._curpos = 0
        endpos = min(self.width, self._curpos + n)
        self._curline[self._curpos : endpos] = bytes([self._color]) * (
            endpos - self._curpos
        )
        self._curpos = endpos

    def _do_uncompressed(self, bits: str) -> None:
        for c in bits:
            self._curline[self._curpos] = int(c)
            self._curpos += 1
            self._flush_line()


class CCITTFaxDecoder(CCITTG4Parser):
    def __init__(
        self,
        params: Dict[str, PDFObject],
    ) -> None:
        width = int_value(params.get("Columns", 1728))
        height = int_value(params.get("Rows", 0))
        bytealign = not not params.get("EncodedByteAlign", False)
        super().__init__(width, height, bytealign=bytealign)
        self.reversed = not not params.get("BlackIs1", False)
        self.eoline = not not params.get("EndOfLine", False)
        self.eoblock = not not params.get("EndOfBlock", True)
        self._buf: List["u8"] = []

    def close(self) -> bytes:
        return bytes(self._buf)

    def output_line(self, y: int, bits: List["u8"]) -> None:
        if self.reversed:
            bits = [x ^ 0xFF for x in bits]
        byte = 0
        for i, b in enumerate(bits):
            if b:
                pos = i & 7
                bit = 0x80 >> pos
                byte |= bit
            if i & 7 == 7:
                self._buf.append(byte)
                byte = 0
        if i & 7 != 7:
            self._buf.append(byte)


class CCITTFaxDecoder1D(CCITTFaxDecoder):
    def feedbytes(self, data: bytes) -> None:
        for byte in data:
            try:
                # bits = "".join(
                # "1" if (byte & m) else "0" for m in (128, 64, 32, 16, 8, 4, 2, 1)
                # )
                # LOG.debug("byte: %s", bits)
                for m in (128, 64, 32, 16, 8, 4, 2, 1):
                    self._parse_bit(byte & m)
            except ByteSkip:
                self._accept = self._parse_horiz
                self._n1 = 0
                self._state = WHITE if self._color else BLACK
                self._node = self._state.root
                self._bits.clear()
                # LOG.debug("=> ByteSkip => %s", self.state_name)
            except InvalidData:
                LOG.warning("Unknown %s code: %r", self.state_name, self.code_bits)
                break
            except EOFB:
                break

    def reset(self) -> None:
        self._y = 0
        self._curline = [1] * self.width
        self._reset_line()
        self._accept = self._parse_horiz
        self._n1 = 0
        self._color = 1
        self._state = WHITE

    def _reset_line(self) -> None:
        # NOTE: do not reset color to white on new line
        self._refline = self._curline
        self._curline = [1] * self.width
        self._curpos = -1

    def _parse_horiz(self, n: BitParserNode) -> BitParserTree:
        if n is None:
            raise InvalidData
        elif n == "e":
            # Soft reset
            self._reset_line()
            self._color = 1
            self._n1 = 0
            return WHITE
        assert isinstance(n, int)
        self._n1 += n
        if n < 64:
            self._do_horizontal_one(self._n1)
            self._n1 = 0
            self._color = 1 - self._color
            self._flush_line()
        return WHITE if self._color else BLACK

    def _flush_line(self) -> None:
        if self._curpos < self.width:
            return
        self.output_line(self._y, self._curline)
        self._y += 1
        self._reset_line()
        if self.bytealign:
            raise ByteSkip


class CCITTFaxDecoderMixed(CCITTFaxDecoder):
    def _parse_mode(self, mode: Any) -> BitParserTree:
        # Act on a code from the leaves of MODE
        if mode == "p":  # twoDimPass
            self._do_pass()
            self._flush_line()
            return MODE
        elif mode == "h":  # twoDimHoriz
            self._n1 = 0
            self._accept = self._parse_horiz1
            if self._color:
                return WHITE
            else:
                return BLACK
        elif mode == "u":  # uncompressed (unsupported by pdf.js?)
            self._accept = self._parse_uncompressed
            return UNCOMPRESSED
        elif mode == "e":
            self._accept = self._parse_next2d
            return NEXT2D
        elif isinstance(mode, str) and mode[0] == "x":
            LOG.warning("Skipping unsupported code: %s (%s)", mode, self.code_bits)
            return MODE
        elif isinstance(mode, int):  # twoDimVert[LR]\d
            self._do_vertical(mode)
            self._flush_line()
            return MODE
        else:
            raise InvalidData(mode)

    def _parse_next2d(self, n: BitParserNode) -> BitParserTree:
        if n:  # 2D mode
            self._accept = self._parse_mode
            return MODE
        # Otherwise, 1D mode
        self._n1 = 0
        self._accept = self._parse_horiz
        return WHITE if self._color else BLACK

    def _parse_horiz(self, n: BitParserNode) -> BitParserTree:
        if n is None:
            raise InvalidData
        elif n == "e":
            # Decide if we continue in 1D mode or not
            self._accept = self._parse_next2d
            return NEXT2D
        assert isinstance(n, int)
        self._n1 += n
        if n < 64:
            self._do_horizontal_one(self._n1)
            self._n1 = 0
            self._color = 1 - self._color
            self._flush_line()
        return WHITE if self._color else BLACK


def ccittfaxdecode(data: bytes, params: Dict[str, PDFObject]) -> bytes:
    LOG.debug("CCITT decode parms: %r", params)
    K = params.get("K", 0)
    if K == -1:
        parser = CCITTFaxDecoder(params)
    elif K == 0:
        parser = CCITTFaxDecoder1D(params)
    else:
        parser = CCITTFaxDecoderMixed(params)
    try:
        parser.feedbytes(data)
    except CCITTException as e:
        LOG.warning("Exception in CCITT parsing: %r", e)
    return parser.close()
