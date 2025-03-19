"""
Benchmark the converter on all of the sample documents.
"""

import logging
import sys
import time
from pathlib import Path

from tests.data import BASEPDFS, PASSWORDS, PDFMINER_BUGS, XFAILS

LOG = logging.getLogger("benchmark-convert")


def benchmark_one_lazy(path: Path):
    """Open one of the documents"""
    import playa

    if path.name in PDFMINER_BUGS or path.name in XFAILS:
        return
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        LOG.info("Reading %s", path)
        with playa.open(path, password=password) as pdf:
            for page in pdf.pages:
                for obj in page:
                    _ = obj.bbox
                    if obj.object_type == "xobject":
                        _ = [objobj.bbox for objobj in obj]


def benchmark_one_pdfminer(path: Path):
    """Open one of the documents"""
    from pdfminer.converter import PDFLayoutAnalyzer
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser

    if path.name in PDFMINER_BUGS or path.name in XFAILS:
        return
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        with open(path, "rb") as infh:
            LOG.debug("Reading %s", path)
            rsrc = PDFResourceManager()
            analyzer = PDFLayoutAnalyzer(rsrc)
            interp = PDFPageInterpreter(rsrc, analyzer)
            pdf = PDFDocument(PDFParser(infh), password=password)
            for page in PDFPage.create_pages(pdf):
                interp.process_page(page)


if __name__ == "__main__":
    # Silence warnings about broken PDFs
    logging.basicConfig(level=logging.ERROR)
    niter = 5
    miner_time = lazy_time = 0.0
    for iter in range(niter + 1):
        for path in BASEPDFS:
            if len(sys.argv) == 1 or "lazy" in sys.argv[1:]:
                start = time.time()
                benchmark_one_lazy(path)
                if iter != 0:
                    lazy_time += time.time() - start
            if len(sys.argv) == 1 or "pdfminer" in sys.argv[1:]:
                start = time.time()
                benchmark_one_pdfminer(path)
                if iter != 0:
                    miner_time += time.time() - start
    print("pdfminer.six took %.2fs / iter" % (miner_time / niter,))
    print("PLAYA (lazy) took %.2fs / iter" % (lazy_time / niter,))
