import re
import unittest
from pathlib import Path

import playa
from playa.pdfstructtree import PDFStructTree

TESTDIR = Path(__file__).parent.parent / "samples"


class TestClass(unittest.TestCase):
    """Test the underlying Structure tree class"""

    def test_structure_tree_class(self):
        with playa.open(TESTDIR / "image_structure.pdf") as pdf:
            stree = PDFStructTree(pdf, next(pdf.get_pages()))
            doc_elem = next(iter(stree))
            assert [k.type for k in doc_elem] == ["P", "P", "Figure"]

    def test_find_all_tree(self):
        """
        Test find_all() and find() on trees
        """
        with playa.open(TESTDIR / "image_structure.pdf") as pdf:
            stree = PDFStructTree(pdf, next(pdf.get_pages()))
            figs = list(stree.find_all("Figure"))
            assert len(figs) == 1
            fig = stree.find("Figure")
            assert fig == figs[0]
            assert stree.find("Fogure") is None
            figs = list(stree.find_all(re.compile(r"Fig.*")))
            assert len(figs) == 1
            figs = list(stree.find_all(lambda x: x.type == "Figure"))
            assert len(figs) == 1
            figs = list(stree.find_all("Foogure"))
            assert len(figs) == 0
            figs = list(stree.find_all(re.compile(r"Fog.*")))
            assert len(figs) == 0
            figs = list(stree.find_all(lambda x: x.type == "Flogger"))
            assert len(figs) == 0

    def test_find_all_element(self):
        """
        Test find_all() and find() on elements
        """
        with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
            stree = PDFStructTree(pdf)
            for list_elem in stree.find_all("L"):
                items = list(list_elem.find_all("LI"))
                assert items
                for item in items:
                    body = list(item.find_all("LBody"))
                    assert body
                    body1 = item.find("LBody")
                    assert body1 == body[0]
                    assert item.find("Loonie") is None

    def test_all_mcids(self):
        """
        Test all_mcids()
        """
        with playa.open(TESTDIR / "2023-06-20-PV.pdf") as pdf:
            # Make sure we can get them with page numbers
            stree = PDFStructTree(pdf)
            sect = next(stree.find_all("Sect"))
            mcids = list(sect.all_mcids())
            pages = set(page for page, mcid in mcids)
            assert 1 in pages
            assert 2 in pages

            page = next(pdf.get_pages())
            stree = PDFStructTree(pdf, page)
            sect = next(stree.find_all("Sect"))
            mcids = list(sect.all_mcids())
            pages = set(page for page, mcid in mcids)
            assert None in pages
            assert 1 not in pages
            assert 2 not in pages
            # Assure that we get the MCIDs for a content element
            for p in sect.find_all("P"):
                # p.mcids is the MCIDs for just this element,
                # all_mcids includes children (unsure why this is
                # different in pdfplumber?)
                assert set(mcid for page, mcid in p.all_mcids()).issuperset(p.mcids)
