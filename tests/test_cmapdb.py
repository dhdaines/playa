"""
Inadequately test CMap parsing and such.
"""

from playa.cmapdb import CMapParser, FileUnicodeMap

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
    assert cmap.cid2unichr == {1: 'x', 2: '̌', 3: 'u'}
