import unittest

from playa.pdfstructtree import PDFStructTree

class TestClass(unittest.TestCase):
    """Test the underlying Structure tree class"""

    def test_structure_tree_class(self):
        path = os.path.join(HERE, "pdfs/image_structure.pdf")
        pdf = pdfplumber.open(path)
        stree = PDFStructTree(pdf, pdf.pages[0])
        doc_elem = next(iter(stree))
        assert [k.type for k in doc_elem] == ["P", "P", "Figure"]

    def test_find_all_tree(self):
        """
        Test find_all() and find() on trees
        """
        path = os.path.join(HERE, "pdfs/image_structure.pdf")
        pdf = pdfplumber.open(path)
        stree = PDFStructTree(pdf, pdf.pages[0])
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
        path = os.path.join(HERE, "pdfs/pdf_structure.pdf")
        pdf = pdfplumber.open(path)
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
        path = os.path.join(HERE, "pdfs/2023-06-20-PV.pdf")
        pdf = pdfplumber.open(path)
        # Make sure we can get them with page numbers
        stree = PDFStructTree(pdf)
        sect = next(stree.find_all("Sect"))
        mcids = list(sect.all_mcids())
        pages = set(page for page, mcid in mcids)
        assert 1 in pages
        assert 2 in pages
        # If we take only a single page there are no page numbers
        # (FIXME: may wish to reconsider this API decision...)
        page = pdf.pages[1]
        stree = PDFStructTree(pdf, page)
        sect = next(stree.find_all("Sect"))
        mcids = list(sect.all_mcids())
        pages = set(page for page, mcid in mcids)
        assert None in pages
        assert 1 not in pages
        assert 2 not in pages
        # Assure that we get the MCIDs for a content element
        for p in sect.find_all("P"):
            assert set(mcid for page, mcid in p.all_mcids()) == set(p.mcids)

    def test_element_bbox(self):
        """
        Test various ways of getting element bboxes
        """
        path = os.path.join(HERE, "pdfs/pdf_structure.pdf")
        pdf = pdfplumber.open(path)
        stree = PDFStructTree(pdf)
        # As BBox attribute
        table = next(stree.find_all("Table"))
        assert tuple(stree.element_bbox(table)) == (56.7, 489.9, 555.3, 542.25)
        # With child elements
        tr = next(table.find_all("TR"))
        assert tuple(stree.element_bbox(tr)) == (56.8, 495.9, 328.312, 507.9)
        # From a specific page it should also work
        stree = PDFStructTree(pdf, pdf.pages[0])
        table = next(stree.find_all("Table"))
        assert tuple(stree.element_bbox(table)) == (56.7, 489.9, 555.3, 542.25)
        tr = next(table.find_all("TR"))
        assert tuple(stree.element_bbox(tr)) == (56.8, 495.9, 328.312, 507.9)
        # Yeah but what happens if you crop the page?
        page = pdf.pages[0].crop((10, 400, 500, 500))
        stree = PDFStructTree(pdf, page)
        table = next(stree.find_all("Table"))
        # The element gets cropped too
        assert tuple(stree.element_bbox(table)) == (56.7, 489.9, 500, 500)
        # And if you crop it out of the page?
        page = pdf.pages[0].crop((0, 0, 560, 400))
        stree = PDFStructTree(pdf, page)
        table = next(stree.find_all("Table"))
        with self.assertRaises(IndexError):
            _ = stree.element_bbox(table)
