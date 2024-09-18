import logging
import time
from io import BufferedReader, BytesIO
from pathlib import Path

from playa.psparser import (
    KEYWORD_DICT_BEGIN,
    KEYWORD_DICT_END,
    KWD,
    LIT,
    PSBaseParser,
)

log = logging.getLogger(Path(__file__).stem)
SIMPLE1 = b"""1 0 obj
<<
 /Type /Catalog
 /Outlines 2 0 R
 /Pages 3 0 R
>>
endobj
"""
SIMPLETOK = [
    1,
    0,
    KWD(b"obj"),
    KEYWORD_DICT_BEGIN,
    LIT("Type"),
    LIT("Catalog"),
    LIT("Outlines"),
    2,
    0,
    KWD(b"R"),
    LIT("Pages"),
    3,
    0,
    KWD(b"R"),
    KEYWORD_DICT_END,
    KWD(b"endobj"),
]


def bench_parser():
    start = time.time()
    parser = PSBaseParser(BufferedReader(BytesIO(SIMPLE1 * 10000)))
    tokens = [tok for pos, tok in list(parser)]
    print("It took", time.time() - start)
    assert tokens == SIMPLETOK * 10000


if __name__ == "__main__":
    bench_parser()
