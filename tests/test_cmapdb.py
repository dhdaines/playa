"""
Inadequately test CMap parsing and such.
"""

from playa.cmapdb import CMapParser, FileUnicodeMap
from playa.font import Type1FontHeaderParser

STREAMDATA = b"""
/CIDInit/ProcSet findresource begin
12 dict begin
begincmap
/CIDSystemInfo<<
/Registry (Adobe)
/Ordering (UCS)
/Supplement 0
>> def
/CMapName/Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<00> <FF>
endcodespacerange
3 beginbfchar
<01> <0078>
<02> <030C>
<03> <0075>
endbfchar
endcmap
CMapName currentdict /CMap defineresource pop
end
end
"""


def test_cmap_parser():
    cmap = FileUnicodeMap()
    cp = CMapParser(cmap, STREAMDATA)
    cp.run()
    assert cmap.cid2unichr == {1: "x", 2: "̌", 3: "u"}


# Basically the sort of stuff we try to find in a Type 1 font
TYPE1DATA = b"""
%!PS-AdobeFont-1.0: MyBogusFont 0.1
/FontName /MyBogusFont def
/Encoding 256 array
0 1 255 {1 index exch /.notdef put} for
dup 48 /zero put
dup 49 /one put
readonly def
"""


def test_t1header_parser():
    parser = Type1FontHeaderParser(TYPE1DATA)
    assert parser.get_encoding() == {
        48: "0",
        49: "1",
    }
