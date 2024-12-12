## PLAYA 0.2.5
- [x] fix incorrect bboxes when rotation is applied
- [x] return more useful names for custom colorspaces/patterns
- [x] run pdf.js test suite
- [ ] implement CMap parsing for CIDs (submit PR to pdfminer)
- [ ] add "default" as a synonym of badly-named "user" space
- [ ] update `pdfplumber` branch and run `pdfplumber` tests in CI
  - [ ] reimplement on top of ContentObject
  - [ ] make a separate directory for third party tests
- [ ] `decode_text` is remarkably slow
- [ ] `render_char` and `render_string` are also quite slow
- [ ] add something inbetween `chars` and full bbox for TextObject
      (what do you actually need for heuristic or model-based
      extraction? probably just `adv`?)
- [ ] remove the rest of the meaningless abuses of `cast`
- [ ] document transformation of bbox attributes on StructElement
- [ ] implement LayoutDict on top of ContentObject
- [ ] maybe add some stuff to LayoutDict?

## PLAYA 0.3 and beyond
- [ ] support ExtGState (submit PR to pdfminer)
- [ ] better API for document outline, destinations, links, etc
- [ ] test coverage and more test coverage
- [ ] support matching ActualText to text objects when possible
  - [ ] if the text object is a single MCS (LibreOffice will do this)
