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


import array
import logging
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Sequence,
    Union,
)
from playa.pdftypes import PDFObject, int_value

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


class BitParserState:
    def __init__(self, name: str) -> None:
        self.root: BitParserNode = [None, None]
        self.name = name

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


MODE = BitParserState("MODE")
MODE.add(0, "1")  # twoDimVert0
MODE.add(+1, "011")  # twoDimVertR1
MODE.add(-1, "010")  # twoDimVertL1
MODE.add("h", "001")  # twoDimHoriz
MODE.add("p", "0001")  # twoDimPass
MODE.add(+2, "000011")  # twoDimVertR2
MODE.add(-2, "000010")  # twoDimVertR3
MODE.add(+3, "0000011")  # twoDimVertR3
MODE.add(-3, "0000010")  # twoDimVertL3
MODE.add("u", "0000001111")  # uncompressed
# These are all unsupported (raise InvalidData)
MODE.add("x1", "0000001000")
MODE.add("x2", "0000001001")
MODE.add("x3", "0000001010")
MODE.add("x4", "0000001011")
MODE.add("x5", "0000001100")
MODE.add("x6", "0000001101")
MODE.add("x7", "0000001110")
MODE.add("e", "000000000001")

NEXT2D = BitParserState("NEXT2D")
NEXT2D.add(0, "1")
NEXT2D.add(1, "0")

WHITE = BitParserState("WHITE")
WHITE.add(0, "00110101")
WHITE.add(1, "000111")
WHITE.add(2, "0111")
WHITE.add(3, "1000")
WHITE.add(4, "1011")
WHITE.add(5, "1100")
WHITE.add(6, "1110")
WHITE.add(7, "1111")
WHITE.add(8, "10011")
WHITE.add(9, "10100")
WHITE.add(10, "00111")
WHITE.add(11, "01000")
WHITE.add(12, "001000")
WHITE.add(13, "000011")
WHITE.add(14, "110100")
WHITE.add(15, "110101")
WHITE.add(16, "101010")
WHITE.add(17, "101011")
WHITE.add(18, "0100111")
WHITE.add(19, "0001100")
WHITE.add(20, "0001000")
WHITE.add(21, "0010111")
WHITE.add(22, "0000011")
WHITE.add(23, "0000100")
WHITE.add(24, "0101000")
WHITE.add(25, "0101011")
WHITE.add(26, "0010011")
WHITE.add(27, "0100100")
WHITE.add(28, "0011000")
WHITE.add(29, "00000010")
WHITE.add(30, "00000011")
WHITE.add(31, "00011010")
WHITE.add(32, "00011011")
WHITE.add(33, "00010010")
WHITE.add(34, "00010011")
WHITE.add(35, "00010100")
WHITE.add(36, "00010101")
WHITE.add(37, "00010110")
WHITE.add(38, "00010111")
WHITE.add(39, "00101000")
WHITE.add(40, "00101001")
WHITE.add(41, "00101010")
WHITE.add(42, "00101011")
WHITE.add(43, "00101100")
WHITE.add(44, "00101101")
WHITE.add(45, "00000100")
WHITE.add(46, "00000101")
WHITE.add(47, "00001010")
WHITE.add(48, "00001011")
WHITE.add(49, "01010010")
WHITE.add(50, "01010011")
WHITE.add(51, "01010100")
WHITE.add(52, "01010101")
WHITE.add(53, "00100100")
WHITE.add(54, "00100101")
WHITE.add(55, "01011000")
WHITE.add(56, "01011001")
WHITE.add(57, "01011010")
WHITE.add(58, "01011011")
WHITE.add(59, "01001010")
WHITE.add(60, "01001011")
WHITE.add(61, "00110010")
WHITE.add(62, "00110011")
WHITE.add(63, "00110100")
WHITE.add(64, "11011")
WHITE.add(128, "10010")
WHITE.add(192, "010111")
WHITE.add(256, "0110111")
WHITE.add(320, "00110110")
WHITE.add(384, "00110111")
WHITE.add(448, "01100100")
WHITE.add(512, "01100101")
WHITE.add(576, "01101000")
WHITE.add(640, "01100111")
WHITE.add(704, "011001100")
WHITE.add(768, "011001101")
WHITE.add(832, "011010010")
WHITE.add(896, "011010011")
WHITE.add(960, "011010100")
WHITE.add(1024, "011010101")
WHITE.add(1088, "011010110")
WHITE.add(1152, "011010111")
WHITE.add(1216, "011011000")
WHITE.add(1280, "011011001")
WHITE.add(1344, "011011010")
WHITE.add(1408, "011011011")
WHITE.add(1472, "010011000")
WHITE.add(1536, "010011001")
WHITE.add(1600, "010011010")
WHITE.add(1664, "011000")
WHITE.add(1728, "010011011")
WHITE.add(1792, "00000001000")
WHITE.add(1856, "00000001100")
WHITE.add(1920, "00000001101")
WHITE.add(1984, "000000010010")
WHITE.add(2048, "000000010011")
WHITE.add(2112, "000000010100")
WHITE.add(2176, "000000010101")
WHITE.add(2240, "000000010110")
WHITE.add(2304, "000000010111")
WHITE.add(2368, "000000011100")
WHITE.add(2432, "000000011101")
WHITE.add(2496, "000000011110")
WHITE.add(2560, "000000011111")
WHITE.add("e", "000000000001")

BLACK = BitParserState("BLACK")
BLACK.add(0, "0000110111")
BLACK.add(1, "010")
BLACK.add(2, "11")
BLACK.add(3, "10")
BLACK.add(4, "011")
BLACK.add(5, "0011")
BLACK.add(6, "0010")
BLACK.add(7, "00011")
BLACK.add(8, "000101")
BLACK.add(9, "000100")
BLACK.add(10, "0000100")
BLACK.add(11, "0000101")
BLACK.add(12, "0000111")
BLACK.add(13, "00000100")
BLACK.add(14, "00000111")
BLACK.add(15, "000011000")
BLACK.add(16, "0000010111")
BLACK.add(17, "0000011000")
BLACK.add(18, "0000001000")
BLACK.add(19, "00001100111")
BLACK.add(20, "00001101000")
BLACK.add(21, "00001101100")
BLACK.add(22, "00000110111")
BLACK.add(23, "00000101000")
BLACK.add(24, "00000010111")
BLACK.add(25, "00000011000")
BLACK.add(26, "000011001010")
BLACK.add(27, "000011001011")
BLACK.add(28, "000011001100")
BLACK.add(29, "000011001101")
BLACK.add(30, "000001101000")
BLACK.add(31, "000001101001")
BLACK.add(32, "000001101010")
BLACK.add(33, "000001101011")
BLACK.add(34, "000011010010")
BLACK.add(35, "000011010011")
BLACK.add(36, "000011010100")
BLACK.add(37, "000011010101")
BLACK.add(38, "000011010110")
BLACK.add(39, "000011010111")
BLACK.add(40, "000001101100")
BLACK.add(41, "000001101101")
BLACK.add(42, "000011011010")
BLACK.add(43, "000011011011")
BLACK.add(44, "000001010100")
BLACK.add(45, "000001010101")
BLACK.add(46, "000001010110")
BLACK.add(47, "000001010111")
BLACK.add(48, "000001100100")
BLACK.add(49, "000001100101")
BLACK.add(50, "000001010010")
BLACK.add(51, "000001010011")
BLACK.add(52, "000000100100")
BLACK.add(53, "000000110111")
BLACK.add(54, "000000111000")
BLACK.add(55, "000000100111")
BLACK.add(56, "000000101000")
BLACK.add(57, "000001011000")
BLACK.add(58, "000001011001")
BLACK.add(59, "000000101011")
BLACK.add(60, "000000101100")
BLACK.add(61, "000001011010")
BLACK.add(62, "000001100110")
BLACK.add(63, "000001100111")
BLACK.add(64, "0000001111")
BLACK.add(128, "000011001000")
BLACK.add(192, "000011001001")
BLACK.add(256, "000001011011")
BLACK.add(320, "000000110011")
BLACK.add(384, "000000110100")
BLACK.add(448, "000000110101")
BLACK.add(512, "0000001101100")
BLACK.add(576, "0000001101101")
BLACK.add(640, "0000001001010")
BLACK.add(704, "0000001001011")
BLACK.add(768, "0000001001100")
BLACK.add(832, "0000001001101")
BLACK.add(896, "0000001110010")
BLACK.add(960, "0000001110011")
BLACK.add(1024, "0000001110100")
BLACK.add(1088, "0000001110101")
BLACK.add(1152, "0000001110110")
BLACK.add(1216, "0000001110111")
BLACK.add(1280, "0000001010010")
BLACK.add(1344, "0000001010011")
BLACK.add(1408, "0000001010100")
BLACK.add(1472, "0000001010101")
BLACK.add(1536, "0000001011010")
BLACK.add(1600, "0000001011011")
BLACK.add(1664, "0000001100100")
BLACK.add(1728, "0000001100101")
BLACK.add(1792, "00000001000")
BLACK.add(1856, "00000001100")
BLACK.add(1920, "00000001101")
BLACK.add(1984, "000000010010")
BLACK.add(2048, "000000010011")
BLACK.add(2112, "000000010100")
BLACK.add(2176, "000000010101")
BLACK.add(2240, "000000010110")
BLACK.add(2304, "000000010111")
BLACK.add(2368, "000000011100")
BLACK.add(2432, "000000011101")
BLACK.add(2496, "000000011110")
BLACK.add(2560, "000000011111")
BLACK.add("e", "000000000001")

UNCOMPRESSED = BitParserState("UNCOMPRESSED")
UNCOMPRESSED.add("1", "1")
UNCOMPRESSED.add("01", "01")
UNCOMPRESSED.add("001", "001")
UNCOMPRESSED.add("0001", "0001")
UNCOMPRESSED.add("00001", "00001")
UNCOMPRESSED.add("00000", "000001")
UNCOMPRESSED.add("T00", "00000011")
UNCOMPRESSED.add("T10", "00000010")
UNCOMPRESSED.add("T000", "000000011")
UNCOMPRESSED.add("T100", "000000010")
UNCOMPRESSED.add("T0000", "0000000011")
UNCOMPRESSED.add("T1000", "0000000010")
UNCOMPRESSED.add("T00000", "00000000011")
UNCOMPRESSED.add("T10000", "00000000010")
UNCOMPRESSED.add("e", "000000000001")


class BitParser:
    _state: BitParserState
    _node: BitParserNode
    _codebits = bytearray()
    _accept: Callable[[BitParserNode], BitParserState]

    def __init__(self) -> None:
        self._pos = 0
        self._node = None

    def _parse_bit(self, x: int) -> None:
        if self._node is None:
            self._node = self._state.root
        bit = not not x
        assert isinstance(self._node, list)
        v = self._node[bit]
        self._codebits.append(ord("1") if bit else ord("0"))
        self._pos += 1
        if isinstance(v, list):
            self._node = v
        else:
            LOG.debug(
                "%s (%d): %s => %r",
                self._state.name,
                self._pos,
                self._codebits.decode("ascii"),
                v,
            )
            self._codebits.clear()
            assert self._accept is not None
            self._state = self._accept(v)
            self._node = self._state.root


class CCITTG4Parser(BitParser):
    _color: int

    def __init__(self, width: int, height: int, bytealign: bool = False) -> None:
        super().__init__()
        self.width = width
        self.height = height
        self.bytealign = bytealign
        self.reset()

    def feedbytes(self, data: bytes) -> None:
        for byte in data:
            try:
                for m in (128, 64, 32, 16, 8, 4, 2, 1):
                    self._parse_bit(byte & m)
            except ByteSkip:
                self._accept = self._parse_mode
                self._state = MODE
            except EOFB:
                break

    def _parse_mode(self, mode: BitParserNode) -> BitParserState:
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
        elif isinstance(mode, int):  # twoDimVert[LR]\d
            self._do_vertical(mode)
            self._flush_line()
            return MODE
        else:
            raise InvalidData(mode)

    def _parse_horiz1(self, n: BitParserNode) -> BitParserState:
        if not isinstance(n, int):
            raise InvalidData
        self._n1 += n
        if n < 64:
            self._n2 = 0
            self._color = 1 - self._color
            self._accept = self._parse_horiz2
        return WHITE if self._color else BLACK

    def _parse_horiz2(self, n: BitParserNode) -> BitParserState:
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

    def _parse_uncompressed(self, bits: BitParserNode) -> BitParserState:
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
        elif len(self._refline) <= i:
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
        self._curline = array.array("b", [1] * self.width)
        self._reset_line()
        self._accept = self._parse_mode
        self._state = MODE

    def output_line(self, y: int, bits: Sequence[int]) -> None:
        print(y, "".join(str(b) for b in bits))

    def _reset_line(self) -> None:
        self._refline = self._curline
        self._curline = array.array("b", [1] * self.width)
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
            elif x1 == len(self._refline) or (
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
            elif x1 == len(self._refline) or (
                self._refline[x1 - 1] == self._color
                and self._refline[x1] != self._color
            ):
                break
            x1 += 1
        while True:
            if x1 == 0:
                if self._color == 0 and self._refline[x1] == self._color:
                    break
            elif x1 == len(self._refline) or (
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
        x = self._curpos
        for _ in range(n1):
            if len(self._curline) <= x:
                break
            self._curline[x] = self._color
            x += 1
        for _ in range(n2):
            if len(self._curline) <= x:
                break
            self._curline[x] = 1 - self._color
            x += 1
        self._curpos = x

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
        self._buf: List[bytearray] = []

    def close(self) -> bytes:
        return b"".join(self._buf)

    def output_line(self, y: int, bits: Sequence[int]) -> None:
        arr = bytearray((len(bits) + 7) // 8)
        if self.reversed:
            bits = [~b for b in bits]
        for i, b in enumerate(bits):
            if b:
                arr[i // 8] += (128, 64, 32, 16, 8, 4, 2, 1)[i % 8]
        self._buf.append(arr)


class CCITTFaxDecoder1D(CCITTFaxDecoder):
    def feedbytes(self, data: bytes) -> None:
        for byte in data:
            try:
                for m in (128, 64, 32, 16, 8, 4, 2, 1):
                    self._parse_bit(byte & m)
            except ByteSkip:
                self._accept = self._parse_horiz1
                self._n1 = 0
                self._state = WHITE if self._color else BLACK
            except EOFB:
                break

    def reset(self) -> None:
        self._y = 0
        self._curline = array.array("b", [1] * self.width)
        self._reset_line()
        self._accept = self._parse_horiz
        self._n1 = 0
        self._color = 1
        self._state = WHITE

    def _reset_line(self) -> None:
        # NOTE: do not reset color to white on new line
        self._refline = self._curline
        self._curline = array.array("b", [1] * self.width)
        self._curpos = -1

    def _parse_horiz(self, n: BitParserNode) -> BitParserState:
        if not isinstance(n, (int, str)):
            raise InvalidData
        elif n == "e":
            # Soft reset
            self._reset_line()
            self._color = 1
            self._n1 = 0
            return WHITE
        self._n1 += n
        if n < 64:
            self._do_horizontal_one(self._n1)
            self._n1 = 0
            self._color = 1 - self._color
            self._flush_line()
        return WHITE if self._color else BLACK

    def _do_horizontal_one(self, n: int) -> None:
        if self._curpos < 0:
            self._curpos = 0
        x = self._curpos
        for _ in range(n):
            if len(self._curline) <= x:
                break
            self._curline[x] = self._color
            x += 1
        self._curpos = x

    def _flush_line(self) -> None:
        if self._curpos < self.width:
            return
        self.output_line(self._y, self._curline)
        self._y += 1
        self._reset_line()
        if self.bytealign:
            raise ByteSkip
        LOG.debug(
            "EndOfBlock %r, EndOfLine %r, row %d of %d",
            self.eoblock,
            self.eoline,
            self._y,
            self.height,
        )


class CCITTFaxDecoderMixed(CCITTFaxDecoder):
    def feedbytes(self, data: bytes) -> None:
        for byte in data:
            try:
                for m in (128, 64, 32, 16, 8, 4, 2, 1):
                    self._parse_bit(byte & m)
            except ByteSkip:
                self._accept = self._parse_mode
                self._state = MODE
            except EOFB:
                break

    def _parse_mode(self, mode: Any) -> BitParserState:
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
        elif isinstance(mode, int):  # twoDimVert[LR]\d
            self._do_vertical(mode)
            self._flush_line()
            return MODE
        else:
            raise InvalidData(mode)

    def _parse_next2d(self, n: BitParserNode) -> BitParserState:
        if n:  # 2D mode
            self._accept = self._parse_mode
            return MODE
        # Otherwise, 1D mode
        self._n1 = 0
        self._accept = self._parse_horiz
        return WHITE if self._color else BLACK

    def reset(self) -> None:
        self._y = 0
        self._curline = array.array("b", [1] * self.width)
        self._reset_line()
        self._accept = self._parse_mode
        self._state = MODE

    def _reset_line(self) -> None:
        self._refline = self._curline
        self._curline = array.array("b", [1] * self.width)
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
            elif x1 == len(self._refline) or (
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
            elif x1 == len(self._refline) or (
                self._refline[x1 - 1] == self._color
                and self._refline[x1] != self._color
            ):
                break
            x1 += 1
        while True:
            if x1 == 0:
                if self._color == 0 and self._refline[x1] == self._color:
                    break
            elif x1 == len(self._refline) or (
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
        x = self._curpos
        for _ in range(n1):
            if len(self._curline) <= x:
                break
            self._curline[x] = self._color
            x += 1
        for _ in range(n2):
            if len(self._curline) <= x:
                break
            self._curline[x] = 1 - self._color
            x += 1
        self._curpos = x

    def _do_uncompressed(self, bits: str) -> None:
        for c in bits:
            self._curline[self._curpos] = int(c)
            self._curpos += 1
            self._flush_line()

    def _parse_horiz(self, n: BitParserNode) -> BitParserState:
        if not isinstance(n, (int, str)):
            raise InvalidData
        elif n == "e":
            # Decide if we continue in 1D mode or not
            self._accept = self._parse_next2d
            return NEXT2D
        self._n1 += n
        if n < 64:
            self._do_horizontal_one(self._n1)
            self._n1 = 0
            self._color = 1 - self._color
            self._flush_line()
        return WHITE if self._color else BLACK

    def _do_horizontal_one(self, n: int) -> None:
        if self._curpos < 0:
            self._curpos = 0
        x = self._curpos
        for _ in range(n):
            if len(self._curline) <= x:
                break
            self._curline[x] = self._color
            x += 1
        self._curpos = x


def ccittfaxdecode(data: bytes, params: Dict[str, PDFObject]) -> bytes:
    LOG.debug("CCITT decode parms: %r", params)
    K = params.get("K", 0)
    if K == -1:
        parser = CCITTFaxDecoder(params)
    elif K == 0:
        parser = CCITTFaxDecoder1D(params)
    else:
        parser = CCITTFaxDecoderMixed(params)
    parser.feedbytes(data)
    return parser.close()
