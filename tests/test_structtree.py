import re
import unittest
from pathlib import Path

import playa
from playa.structtree import StructTree

TESTDIR = Path(__file__).parent.parent / "samples"


class TestClass(unittest.TestCase):
    """Test the underlying Structure tree class"""

    def test_structure_tree_class(self) -> None:
        with playa.open(TESTDIR / "image_structure.pdf") as pdf:
            stree = StructTree(pdf, [pdf.pages[0]])
            doc_elem = next(iter(stree))
            assert [k.type for k in doc_elem] == ["P", "P", "Figure"]

    def test_find_all_tree(self) -> None:
        """
        Test find_all() and find() on trees
        """
        with playa.open(TESTDIR / "image_structure.pdf") as pdf:
            stree = StructTree(pdf, [pdf.pages[0]])
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

    def test_find_all_element(self) -> None:
        """
        Test find_all() and find() on elements
        """
        with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
            stree = StructTree(pdf)
            for list_elem in stree.find_all("L"):
                items = list(list_elem.find_all("LI"))
                assert items
                for item in items:
                    body = list(item.find_all("LBody"))
                    assert body
                    body1 = item.find("LBody")
                    assert body1 == body[0]
                    assert item.find("Loonie") is None

    def test_all_mcids(self) -> None:
        """
        Test all_mcids()
        """
        with playa.open(TESTDIR / "2023-06-20-PV.pdf") as pdf:
            # Make sure we can get them with page numbers
            stree = StructTree(pdf)
            sect = next(stree.find_all("Sect"))
            mcids = list(sect.all_mcids())
            page_indices = set(page for page, mcid in mcids)
            assert 0 in page_indices
            assert 1 in page_indices

            stree = StructTree(pdf, [pdf.pages[1]])
            sect = next(stree.find_all("Sect"))
            mcids = list(sect.all_mcids())
            page_indices = set(page for page, mcid in mcids)
            assert page_indices == {1}
            for p in sect.find_all("P"):
                assert set(mcid for page, mcid in p.all_mcids()) == set(p.mcids)
