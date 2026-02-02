"""
Benchmark latency of opening PDFs (possibly other things soon).
"""

import logging
import time
from pathlib import Path

import playa

LOG = logging.getLogger("benchmark-convert")
# Use a standard benchmark set to make version comparisons possible
CONTRIB = Path(__file__).parent.parent / "samples" / "contrib"
PDFS = [
    "2023-04-06-ODJ et Résolutions-séance xtra 6 avril 2023.pdf",
    "2023-06-20-PV.pdf",
    "PSC_Station.pdf",
    "Rgl-1314-2021-DM-Derogations-mineures.pdf",
    "issue-886-xref-stream-widths.pdf",
    "issue-146-broken-xref-and-streams.pdf",
    "issue-1008-inline-ascii85.pdf",
    "evil-pi-to-100000-digits.pdf",
]

if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    cat_time = fonts_time = open_time = page0_time = 0.0
    nfiles = 0
    niter = 5
    for iter in range(niter + 1):
        for name in PDFS:
            path = CONTRIB / name
            start = time.time()
            pdf = playa.open(path)
            if iter != 0:
                open_time += time.time() - start
                nfiles += 1
            cat = pdf.catalog
            if iter != 0:
                cat_time += time.time() - start
            try:
                page = pdf.pages[0]
            except IndexError:
                continue
            if iter != 0:
                page0_time += time.time() - start
            fonts = page.fonts
            if iter != 0:
                fonts_time += time.time() - start

    print("Open took %.3f ms / file" % (open_time / nfiles * 1000,))
    print("Catalog took %.3f ms / file" % (cat_time / nfiles * 1000,))
    print("Page 0 took %.3f ms / file" % (page0_time / nfiles * 1000,))
    print("Page 0 Fonts took %.3f ms / file" % (fonts_time / nfiles * 1000,))
