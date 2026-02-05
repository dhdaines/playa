"""
Get statistics on latency for all the PDFs
"""

import logging
import math
import sys
import time
from pathlib import Path

import playa
from .data import ALLPDFS, XFAILS, PASSWORDS

HERE = Path.cwd()


def main() -> None:
    open_time = []
    cat_time = []
    page_time = []
    logging.basicConfig(level=logging.ERROR)
    print("recalculating", end="", file=sys.stderr, flush=True)
    for path in ALLPDFS:
        p = Path(str(path.values[0]))
        if p.name in XFAILS:
            continue
        passwords = PASSWORDS.get(p.name, [""])
        for password in passwords:
            try:
                start = time.time()
                pdf = playa.open(p, password=password)
                open_time.append(((time.time() - start) * 1000, p.relative_to(HERE)))
                _ = pdf.catalog
                cat_time.append(((time.time() - start) * 1000, p.relative_to(HERE)))
                try:
                    _ = next(iter(pdf.pages))
                    page_time.append(
                        ((time.time() - start) * 1000, p.relative_to(HERE))
                    )
                except StopIteration:
                    pass
                print(".", end="", file=sys.stderr, flush=True)
            except playa.PDFEncryptionError:
                pass
    print(file=sys.stderr)
    report("open", open_time)
    print()
    report("catalog", cat_time)
    print()
    report("page 1", page_time)


def report(name: str, stats: list[tuple[float, Path]]) -> None:
    stats.sort(reverse=True)
    nstats = len(stats)
    print(f"{name}:")
    # We actualy do care a bit more about the mean than the median...
    mean_time = sum(t for t, p in stats) / nstats
    var_time = sum((t - mean_time) ** 2 for t, p in stats) / (nstats - 1)
    std_time = math.sqrt(var_time)
    print("  mean: %.2fms std: %.2fms" % (mean_time, std_time))
    print("  median: %.2fms %s" % stats[nstats // 2])
    print("  max: %.2fms %s" % stats[0])


if __name__ == "__main__":
    main()
