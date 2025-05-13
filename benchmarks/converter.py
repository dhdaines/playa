"""
Benchmark the converter on all of the sample documents.
"""

import logging
import sys
import time
from pathlib import Path


LOG = logging.getLogger("benchmark-convert")
# Use a standard benchmark set to make version comparisons possible
CONTRIB = Path(__file__).parent.parent / "samples" / "contrib"
PDFS = [
    "2023-04-06-ODJ et Résolutions-séance xtra 6 avril 2023.pdf",
    "2023-06-20-PV.pdf",
    "PSC_Station.pdf",
    "Rgl-1314-2021-DM-Derogations-mineures.pdf",
]


def benchmark_one_lazy(path: Path):
    """Open one of the documents"""
    import playa

    with playa.open(path) as pdf:
        for page in pdf.pages:
            for obj in page.flatten():
                _ = obj.bbox


def benchmark_one_pdfminer(path: Path):
    """Open one of the documents"""
    from pdfminer.converter import PDFLayoutAnalyzer
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser

    with open(path, "rb") as infh:
        rsrc = PDFResourceManager()
        analyzer = PDFLayoutAnalyzer(rsrc)
        interp = PDFPageInterpreter(rsrc, analyzer)
        pdf = PDFDocument(PDFParser(infh))
        for page in PDFPage.create_pages(pdf):
            interp.process_page(page)


if __name__ == "__main__":
    # Silence warnings about broken PDFs
    logging.basicConfig(level=logging.ERROR)
    niter = 5
    miner_time = lazy_time = 0.0
    for iter in range(niter + 1):
        for name in PDFS:
            path = CONTRIB / name
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
    print("pdfminer.six took %.2f s / iter" % (miner_time / niter,))
    print("PLAYA (lazy) took %.2f s / iter" % (lazy_time / niter,))
