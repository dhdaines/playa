## PLAYA 0.2
- [ ] run `pdfplumber` tests in CI
  - [ ] make a separate directory for third party tests
- [ ] make a proper schema for LayoutObject, document it, and communicate it to Polars
- [ ] notably NamedTuple things (Color, ColorSpace) should be Tuples in LayoutObject
- [ ] make TextState conform to PDF spec (leading and line matrix) and document it
- [ ] expose more of TextState in LayoutObject (render mode in particular - OCRmyPDF)
- [ ] do not try to map characters with no ToUnicode and no Encoding (OCRmyPDF)
- [ ] incorporate ctm into GraphicState
- [ ] properly support Pattern color space (uncolored tiling patterns) the
  way pdfplumber expects it to work (it does not)
- [ ] `decode_text` is remarkably slow
- [ ] `render_char` and `render_string` are also quite slow
- [ ] remove the rest of the meaningless abuses of `cast`

## PLAYA 0.3 and beyond
- [ ] support `unstructured.io` as a user as well as `pdfplumber` (make PR)
- [ ] support `OCRmyPDF` as a user as well as `pdfplumber` (make PR)
- [ ] implement LayoutObject on top of ContentObject
- [ ] better API for document outline, destinations, and targets
- [ ] test coverage and more test coverage
- [ ] run pdf.js test suite
- [ ] support matching ActualText to text objects when possible
  - [ ] if the text object is a single MCS (LibreOffice will do this)
