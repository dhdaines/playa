## PLAYA 0.2.5
- [x] implement CMap parsing for Encoding CMaps
- [x] add "default" as a synonym of badly-named "user" space
- [x] update `pdfplumber` branch and run `pdfplumber` tests in CI
  - [x] reimplement on top of ContentObject

## PLAYA 0.2.x
- [ ] work around invalid ToUnicode CMaps
- [ ] `decode_text` is remarkably slow
- [ ] `render_char` and `render_string` are also quite slow
- [ ] add something inbetween `chars` and full bbox for TextObject
      (what do you actually need for heuristic or model-based
      extraction? probably just `adv`?)
- [ ] remove the rest of the meaningless abuses of `cast`
- [ ] document how to transform bbox attributes on StructElement,
      Destination, etc (but you should just use "default" space)
- [ ] deprecate LayoutDict

## PLAYA 0.3 and beyond
- [ ] make the structure tree lazy
- [ ] support ExtGState (submit PR to pdfminer)
- [ ] better API for document outline, destinations, links, etc
- [ ] test coverage and more test coverage
- [ ] support matching ActualText to text objects when possible
  - [ ] if the text object is a single MCS (LibreOffice will do this)
