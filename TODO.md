## PLAYA 0.2
- [x] expose form XObjects on Page to allow getting only their contents
- [x] expose form XObject IDs in LayoutDict
- [x] make TextState conform to PDF spec (leading and line matrix) and document it
- [x] expose more of TextState in LayoutDict (render mode in particular - OCRmyPDF)
- [x] do not try to map characters with no ToUnicode and no Encoding (OCRmyPDF)
- [x] properly support Pattern color space (uncolored tiling patterns) the
      way pdfplumber expects it to work
- [x] support marked content points as ContentObjects
- [x] document ContentObjects
- [ ] make a proper schema for LayoutDict, document it, and communicate it to Polars
- [ ] separate color values and patterns in LayoutDict

## PLAYA 0.2.x
- [ ] update `pdfplumber` branch and run `pdfplumber` tests in CI
  - [ ] make a separate directory for third party tests
- [ ] fix incorrect bboxes when rotation/skewing is applied (performance hit...)
- [ ] `decode_text` is remarkably slow
- [ ] `render_char` and `render_string` are also quite slow
- [ ] remove the rest of the meaningless abuses of `cast`
- [ ] document transformation of bbox attributes on StructElement

## PLAYA 0.3 and beyond
- [ ] support ExtGState (TODO in pdfminer as well, submit patch)
- [ ] support `unstructured.io` as a user as well as `pdfplumber` (make PR)
  - it uses the default pdfminer analysis (when laparams is not None)
  - decide if we want to do any layout analysis or not...
- [ ] support `OCRmyPDF` as a user as well as `pdfplumber` (make PR)
  - it also uses the default pdfminer analysis
  - decide if we want to do any layout analysis or not...
- [ ] implement LayoutDict on top of ContentObject
- [ ] better API for document outline, destinations, and targets
- [ ] test coverage and more test coverage
- [ ] run pdf.js test suite
- [ ] support matching ActualText to text objects when possible
  - [ ] if the text object is a single MCS (LibreOffice will do this)
