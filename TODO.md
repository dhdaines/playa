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
