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


def benchmark_latency(*, ncpus: int = 1) -> None:
    cat_time = fonts_time = open_time = page0_time = 0.0
    nfiles = 0
    niter = 5
    for idx in range(niter + 1):
        for name in PDFS:
            path = CONTRIB / name
            start = time.time()
            pdf = playa.open(path, max_workers=ncpus)
            if idx != 0:
                open_time += time.time() - start
                nfiles += 1
            _ = pdf.catalog
            if idx != 0:
                cat_time += time.time() - start
            try:
                page = next(iter(pdf.pages))
            except StopIteration:
                continue
            if idx != 0:
                page0_time += time.time() - start
            _ = page.fonts
            if idx != 0:
                fonts_time += time.time() - start

    print("PLAYA (%d cpu%s)" % (ncpus, "s" if ncpus > 1 else ""))
    print("Open took %.3f ms / file" % (open_time / nfiles * 1000,))
    print("Catalog took %.3f ms / file" % (cat_time / nfiles * 1000,))
    print("Page 0 took %.3f ms / file" % (page0_time / nfiles * 1000,))
    print("Page 0 Fonts took %.3f ms / file" % (fonts_time / nfiles * 1000,))


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    # Benchmark latency without parallelism
    benchmark_latency(ncpus=1)
    # Ensure that parallelism doesn't add latency
    benchmark_latency(ncpus=2)
