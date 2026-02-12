import time
from pathlib import Path
from statistics import mean

import playa
from playa.interp import LazyInterpreter
from playa.parser import Lexer, ObjectParser

CONTRIB = Path(__file__).parent.parent / "samples" / "contrib"


def main():
    with playa.open(CONTRIB / "many_objects.pdf") as pdf:
        page = pdf.pages[12]
        data = next(page.streams).buffer
        times = []
        niter = 2
        for idx in range(niter + 1):
            start = time.time()
            for _ in Lexer(data):
                pass
            if idx:
                times.append(time.time() - start)
        if times:
            print(f"Lexer: {mean(times) * 1000:.2f}ms")

        times = []
        niter = 2
        for idx in range(niter + 1):
            start = time.time()
            for _ in ObjectParser(data):
                pass
            if idx:
                times.append(time.time() - start)
        if times:
            print(f"ObjectParser: {mean(times) * 1000:.2f}ms")

        times = []
        for idx in range(niter + 1):
            start = time.time()
            interp = LazyInterpreter(page, [next(page.streams)])
            interp._dispatch.clear()
            for _ in interp:
                pass
            if idx:
                times.append(time.time() - start)
        if times:
            print(f"Null interpreter: {mean(times) * 1000:.2f}ms")

        times = []
        for idx in range(niter + 1):
            start = time.time()
            interp = LazyInterpreter(page, page.streams)
            for _ in interp:
                pass
            if idx:
                times.append(time.time() - start)
        if times:
            print(f"Full interpreter: {mean(times) * 1000:.2f}ms")


if __name__ == '__main__':
    main()
