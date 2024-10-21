"""
Benchmark the converter on all of the sample documents.
"""

import logging
import time
from pathlib import Path

LOG = logging.getLogger("benchmark-convert")
TESTDIR = Path(__file__).parent.parent / "samples"
ALLPDFS = [
    path for path in TESTDIR.glob("**/*.pdf") if not path.name.startswith("issue-")
]
PASSWORDS = {
    "base.pdf": ["foo"],
    "rc4-40.pdf": ["foo"],
    "rc4-128.pdf": ["foo"],
    "aes-128.pdf": ["foo"],
    "aes-128-m.pdf": ["foo"],
    "aes-256.pdf": ["foo"],
    "aes-256-m.pdf": ["foo"],
    "aes-256-r6.pdf": ["usersecret", "ownersecret"],
}


def benchmark_one_pdf(path: Path):
    """Open one of the documents"""
    import playa
    from playa.converter import PDFPageAggregator
    from playa.pdfinterp import PDFPageInterpreter, PDFResourceManager

    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        LOG.debug("Reading %s", path)
        with playa.open(TESTDIR / path, password=password) as pdf:
            # Seriously WTF is all this... just to get a page... OMG
            rsrc = PDFResourceManager()
            agg = PDFPageAggregator(rsrc, pageno=1)
            interp = PDFPageInterpreter(rsrc, agg)
            for page in pdf.pages:
                interp.process_page(page)


def benchmark_one_pdfminer(path: Path):
    """Open one of the documents"""
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser

    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        with open(TESTDIR / path, "rb") as infh:
            LOG.debug("Reading %s", path)
            rsrc = PDFResourceManager()
            agg = PDFPageAggregator(rsrc, pageno=1)
            interp = PDFPageInterpreter(rsrc, agg)
            pdf = PDFDocument(PDFParser(infh), password=password)
            for page in PDFPage.create_pages(pdf):
                interp.process_page(page)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start = time.time()
    for path in ALLPDFS:
        benchmark_one_pdf(path)
    LOG.info("PLAYA took %f", time.time() - start)
    start = time.time()
    for path in ALLPDFS:
        benchmark_one_pdfminer(path)
    LOG.info("pdfminer.six took %f", time.time() - start)
