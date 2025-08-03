"""
Convert glyph list into Python code.
"""

from typing import TextIO


def convert_glyphlist(fileinput: TextIO) -> None:
    """Convert a glyph list into a python representation."""
    state = 0
    for line in fileinput:
        line = line.strip()
        if not line or line.startswith("#"):
            if state == 1:
                state = 2
                print("}\n")
            print(line)
            continue
        if state == 0:
            print("\nglyphname2unicode = {")
            state = 1
        (name, x) = line.split(";")
        codes = x.split(" ")
        print(
            " {!r}: u'{}',".format(name, "".join("\\u%s" % code for code in codes)),
        )


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "glyphlist", type=argparse.FileType("r"), help="Adobe glyph list to convert"
    )
    args = parser.parse_args()
    convert_glyphlist(args.glyphlist)


if __name__ == "__main__":
    main()
