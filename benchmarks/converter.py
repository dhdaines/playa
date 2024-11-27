"""
Benchmark the converter on all of the sample documents.
"""

import logging
import sys
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
PDFMINER_BUGS = {
    "issue-449-vertical.pdf",
    "issue_495_pdfobjref.pdf",
    "issue-1008-inline-ascii85.pdf",
    "rotated.pdf",
}
XFAILS = {
    "bogus-stream-length.pdf",
}


def benchmark_one_pdf(path: Path):
    """Open one of the documents"""
    import playa

    if path.name in PDFMINER_BUGS or path.name in XFAILS:
        return
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        LOG.info("Reading %s", path)
        with playa.open(path, password=password) as pdf:
            for page in pdf.pages:
                _ = list(page.layout)


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
    from pdfminer.converter import PDFPageAggregator
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
            agg = PDFPageAggregator(rsrc, pageno=1)
            interp = PDFPageInterpreter(rsrc, agg)
            pdf = PDFDocument(PDFParser(infh), password=password)
            for page in PDFPage.create_pages(pdf):
                interp.process_page(page)


if __name__ == "__main__":
    # Silence warnings about broken PDFs
    logging.basicConfig(level=logging.ERROR)
    niter = 10
    miner_time = beach_time = lazy_time = 0.0
    for iter in range(niter + 1):
        for path in ALLPDFS:
            if len(sys.argv) == 1 or "eager" in sys.argv[1:]:
                start = time.time()
                benchmark_one_pdf(path)
                if iter != 0:
                    beach_time += time.time() - start
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
    print("PLAYA (eager) took %.2fs / iter" % (beach_time / niter,))
    print("PLAYA (lazy) took %.2fs / iter" % (lazy_time / niter,))
