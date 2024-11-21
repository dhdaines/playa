import logging
import tempfile
import time
from io import BytesIO
from pathlib import Path

log = logging.getLogger(Path(__file__).stem)
TESTDIR = Path(__file__).parent.parent / "samples"
DATA = rb"""
1 0 5 30 6 46 9 76 10 93 13 123 14 139 17 169 18 202 19 234
20 366 21 501 22 636 23 771 26 906 27 949 28 993 3 1037 24 1080 34 1157
36 1249 7 1292 33 1336 38 1401 40 1493 11 1536 37 1580 42 1645 44 1737 41 1780
46 1833 15 1925 45 1969 48 2034 49 2439 50 2877 52 3323 54 3602 56 3883 30 4119
29 4244 31 4369 32 4493 57 4564 16 4621 12 4679 8 4749 4 4817 58 4872 59 5028
60 5151 61 5213 62 5233
<< /S /GoTo /D (section.1) >>
(First section)
<< /S /GoTo /D (section.2) >>
(Second section)
<< /S /GoTo /D (section.3) >>
(Third section)
<< /S /GoTo /D (section.4) >>
(Heading on Level 1 \(section\))
<< /S /GoTo /D [19 0 R /Fit] >>
<<
/Type /Page
/Contents 25 0 R
/Resources 24 0 R
/MediaBox [0 0 612 792]
/Parent 32 0 R
/Annots [ 20 0 R 21 0 R 22 0 R 23 0 R ]
>>
<<
/Type /Annot
/Subtype /Link
/Border[0 0 1]/H/I/C[1 0 0]
/Rect [132.772 634.321 212.206 643.232]
/A << /S /GoTo /D (section.1) >>
>>
<<
/Type /Annot
/Subtype /Link
/Border[0 0 1]/H/I/C[1 0 0]
/Rect [132.772 612.403 223.288 621.314]
/A << /S /GoTo /D (section.2) >>
>>
<<
/Type /Annot
/Subtype /Link
/Border[0 0 1]/H/I/C[1 0 0]
/Rect [132.772 590.486 216.722 599.397]
/A << /S /GoTo /D (section.3) >>
>>
<<
/Type /Annot
/Subtype /Link
/Border[0 0 1]/H/I/C[1 0 0]
/Rect [132.772 566.077 294.043 578.032]
/A << /S /GoTo /D (section.4) >>
>>
<<
/D [19 0 R /XYZ 132.768 705.06 null]
>>
<<
/D [19 0 R /XYZ 133.768 667.198 null]
>>
<<
/D [19 0 R /XYZ 133.768 675.168 null]
>>
<<
/D [19 0 R /XYZ 133.768 552.06 null]
>>
<<
/Font << /F26 29 0 R /F27 30 0 R /F8 31 0 R >>
/ProcSet [ /PDF /Text ]
>>
<<
/Type /Page
/Contents 35 0 R
/Resources 33 0 R
/MediaBox [0 0 612 792]
/Parent 32 0 R
>>
<<
/D [34 0 R /XYZ 132.768 705.06 null]
>>
<<
/D [34 0 R /XYZ 133.768 667.198 null]
>>
<<
/Font << /F26 29 0 R /F8 31 0 R >>
/ProcSet [ /PDF /Text ]
>>
<<
/Type /Page
/Contents 39 0 R
/Resources 37 0 R
/MediaBox [0 0 612 792]
/Parent 32 0 R
>>
<<
/D [38 0 R /XYZ 132.768 705.06 null]
>>
<<
/D [38 0 R /XYZ 133.768 667.198 null]
>>
<<
/Font << /F26 29 0 R /F8 31 0 R >>
/ProcSet [ /PDF /Text ]
>>
<<
/Type /Page
/Contents 43 0 R
/Resources 41 0 R
/MediaBox [0 0 612 792]
/Parent 32 0 R
>>
<<
/D [42 0 R /XYZ 132.768 705.06 null]
>>
<<
/Font << /F8 31 0 R >>
/ProcSet [ /PDF /Text ]
>>
<<
/Type /Page
/Contents 47 0 R
/Resources 45 0 R
/MediaBox [0 0 612 792]
/Parent 32 0 R
>>
<<
/D [46 0 R /XYZ 133.768 667.198 null]
>>
<<
/Font << /F26 29 0 R /F8 31 0 R >>
/ProcSet [ /PDF /Text ]
>>
[277.8 500 500 500 500 500 500 500 500 500 500 500 277.8 277.8 277.8 777.8 472.2 472.2 777.8 750 708.3 722.2 763.9 680.6 652.8 784.7 750 361.1 513.9 777.8 625 916.7 750 777.8 680.6 777.8 736.1 555.6 722.2 750 750 1027.8 750 750 611.1 277.8 500 277.8 500 277.8 277.8 500 555.6 444.4 555.6 444.4 305.6 500 555.6 277.8 305.6 527.8 277.8 833.3 555.6 500 555.6 527.8 391.7 394.4 388.9 555.6 527.8 722.2 527.8]
[447.2 447.2 575 894.4 319.4 383.3 319.4 575 575 575 575 575 575 575 575 575 575 575 319.4 319.4 350 894.4 543.1 543.1 894.4 869.4 818.1 830.6 881.9 755.6 723.6 904.2 900 436.1 594.4 901.4 691.7 1091.7 900 863.9 786.1 863.9 862.5 638.9 800 884.7 869.4 1188.9 869.4 869.4 702.8 319.4 602.8 319.4 575 319.4 319.4 559 638.9 511.1 638.9 527.1 351.4 575 638.9 319.4 351.4 606.9 319.4 958.3 638.9 575 638.9 606.9 473.6 453.6 447.2 638.9 606.9]
[437.5 437.5 562.5 875 312.5 375 312.5 562.5 562.5 562.5 562.5 562.5 562.5 562.5 562.5 562.5 562.5 562.5 312.5 312.5 342.6 875 531.2 531.2 875 849.5 799.8 812.5 862.3 738.4 707.2 884.3 879.6 419 581 880.8 675.9 1067.1 879.6 844.9 768.5 844.9 839.1 625 782.4 864.6 849.5 1162 849.5 849.5 687.5 312.5 581 312.5 562.5 312.5 312.5 546.9 625 500 625 513.3 343.7 562.5 625 312.5 343.7 593.7 312.5 937.5 625 562.5 625 593.7 459.5 443.8 437.5 625 593.7]
<<
/Type /FontDescriptor
/FontName /ZSHFTL+CMBX10
/Flags 4
/FontBBox [-56 -250 1164 750]
/Ascent 694
/CapHeight 686
/Descent -194
/ItalicAngle 0
/StemV 114
/XHeight 444
/CharSet (/F/H/L/S/T/a/c/d/e/four/g/h/i/l/n/o/one/parenleft/parenright/r/s/t/three/two/v)
/FontFile 51 0 R
>>
<<
/Type /FontDescriptor
/FontName /NJBTSJ+CMBX12
/Flags 4
/FontBBox [-53 -251 1139 750]
/Ascent 694
/CapHeight 686
/Descent -194
/ItalicAngle 0
/StemV 109
/XHeight 444
/CharSet (/C/F/H/L/S/T/a/c/d/e/four/g/h/i/l/n/o/one/parenleft/parenright/r/s/t/three/two/v)
/FontFile 53 0 R
>>
<<
/Type /FontDescriptor
/FontName /PQDURT+CMR10
/Flags 4
/FontBBox [-40 -250 1009 750]
/Ascent 694
/CapHeight 683
/Descent -194
/ItalicAngle 0
/StemV 69
/XHeight 431
/CharSet (/M/S/e/h/i/m/o/one/period/r/t/two/v/x)
/FontFile 55 0 R
>>
<<
/Type /Font
/Subtype /Type1
/BaseFont /ZSHFTL+CMBX10
/FontDescriptor 52 0 R
/FirstChar 40
/LastChar 118
/Widths 49 0 R
>>
<<
/Type /Font
/Subtype /Type1
/BaseFont /NJBTSJ+CMBX12
/FontDescriptor 54 0 R
/FirstChar 40
/LastChar 118
/Widths 50 0 R
>>
<<
/Type /Font
/Subtype /Type1
/BaseFont /PQDURT+CMR10
/FontDescriptor 56 0 R
/FirstChar 46
/LastChar 120
/Widths 48 0 R
>>
<<
/Type /Pages
/Count 5
/Kids [19 0 R 34 0 R 38 0 R 42 0 R 46 0 R]
>>
<<
/Type /Outlines
/First 4 0 R
/Last 16 0 R
/Count 4
>>
<<
/Title 17 0 R
/A 14 0 R
/Parent 57 0 R
/Prev 12 0 R
>>
<<
/Title 13 0 R
/A 10 0 R
/Parent 57 0 R
/Prev 8 0 R
/Next 16 0 R
>>
<<
/Title 9 0 R
/A 6 0 R
/Parent 57 0 R
/Prev 4 0 R
/Next 12 0 R
>>
<<
/Title 5 0 R
/A 1 0 R
/Parent 57 0 R
/Next 8 0 R
>>
<<
/Names [(Doc-Start) 27 0 R (page.1) 40 0 R (page.2) 44 0 R (page.iii) 26 0 R (page.iv) 36 0 R (section*.1) 28 0 R]
/Limits [(Doc-Start) (section*.1)]
>>
<<
/Names [(section.1) 3 0 R (section.2) 7 0 R (section.3) 11 0 R (section.4) 15 0 R]
/Limits [(section.1) (section.4)]
>>
<<
/Kids [58 0 R 59 0 R]
/Limits [(Doc-Start) (section.4)]
>>
<<
/Dests 60 0 R
>>
<<
/Type /Catalog
/Pages 32 0 R
/Outlines 57 0 R
/Names 61 0 R
/PageMode/UseOutlines/PageLabels<</Nums[0<</S/r /St 3>>2<</S/D>>4<</S/D>>]>>
/OpenAction 18 0 R
>>
"""


def bench_bytes():
    from playa.parser import Lexer

    runs = 100
    start = time.time()
    parser = Lexer(DATA * runs)
    _ = list(parser)
    print(
        "PLAYA Lexer (bytes): %fms / run" % ((time.time() - start) / runs * 1000),
    )


def bench_mmap():
    import mmap

    from playa.parser import Lexer

    with tempfile.NamedTemporaryFile() as tf:
        runs = 100
        with open(tf.name, "wb") as outfh:
            outfh.write(DATA * runs)
        with open(tf.name, "rb") as infh:
            start = time.time()
            mapping = mmap.mmap(infh.fileno(), 0, access=mmap.ACCESS_READ)
            parser = Lexer(mapping)
            _ = list(parser)
            print(
                "PLAYA Lexer (mmap): %fms / run"
                % ((time.time() - start) / runs * 1000),
            )


def bench_playa():
    from playa.document import Document

    bench_bytes()
    bench_mmap()

    runs = 20
    start = time.time()
    for _ in range(runs):
        with open(TESTDIR / "contrib" / "pagelabels.pdf", "rb") as infh:
            doc = Document(infh)
            page = doc.pages[0]
            _ = list(page.layout)
    print(
        "PLAYA Interpreter: %dms / run" % ((time.time() - start) / runs * 1000),
    )


def bench_pdfminer():
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser
    from pdfminer.psparser import PSEOF, PSBaseParser

    runs = 100
    start = time.time()
    parser = PSBaseParser(BytesIO(DATA * runs))
    while True:
        try:
            _ = parser.nexttoken()
        except PSEOF:
            break
    print(
        "pdfminer.six Lexer (BytesIO): %fms / run"
        % ((time.time() - start) / runs * 1000),
    )
    with tempfile.NamedTemporaryFile() as tf:
        runs = 100
        with open(tf.name, "wb") as outfh:
            outfh.write(DATA * runs)
        with open(tf.name, "rb") as infh:
            parser = PSBaseParser(infh)
            while True:
                try:
                    _ = parser.nexttoken()
                except PSEOF:
                    break
            print(
                "pdfminer.six Lexer (BinaryIO): %fms / run"
                % ((time.time() - start) / runs * 1000),
            )
    runs = 20
    start = time.time()
    for _ in range(runs):
        with open(TESTDIR / "contrib" / "pagelabels.pdf", "rb") as infh:
            rsrc = PDFResourceManager()
            agg = PDFPageAggregator(rsrc, pageno=1)
            interp = PDFPageInterpreter(rsrc, agg)
            doc = PDFDocument(PDFParser(infh))
            page = next(PDFPage.create_pages(doc))
            interp.process_page(page)
    print(
        "pdfminer.six Interpreter: %dms / run" % ((time.time() - start) / runs * 1000),
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2 or sys.argv[1] == "pdfminer":
        bench_pdfminer()
    if len(sys.argv) < 2 or sys.argv[1] == "playa":
        bench_playa()
    if len(sys.argv) > 1 and sys.argv[1] == "bytes":
        bench_bytes()
    if len(sys.argv) > 1 and sys.argv[1] == "mmap":
        bench_mmap()
