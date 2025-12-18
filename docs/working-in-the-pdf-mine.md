# Working in the PDF mine

`pdfminer.six` is widely used for text extraction and layout analysis
due to its liberal licensing terms.  Unfortunately it is quite slow
and contains many bugs.  Now you can use PLAYA instead:

```python
from playa.miner import extract, LAParams

laparams = LAParams()
for page in extract(path, laparams):
    # do something
```

This is generally faster than `pdfminer.six`.  You can often make it
even faster on large documents by running in parallel with the
`max_workers` argument, which is the same as the one you will find in
`concurrent.futures.ProcessPoolExecutor`.  If you pass `None` it will
use all your CPUs, but due to some unavoidable overhead, it usually
doesn't help to use more than 2-4:

```
for page in extract(path, laparams, max_workers=2):
    # do something
```

There are a few differences with `pdfminer.six` (some might call them
bug fixes):

- By default, if you do not pass the `laparams` argument to `extract`,
  no layout analysis at all is done.  This is different from
  `extract_pages` in `pdfminer.six` which will set some default
  parameters for you.  If you don't see any `LTTextBox` items in your
  `LTPage` then this is why!
- Rectangles are recognized correctly in some cases where
  `pdfminer.six` thought they were "curves".
- Colours and colour spaces are the PLAYA versions, which do not
  correspond to what `pdfminer.six` gives you, because what
  `pdfminer.six` gives you is not useful and often wrong.
- You have access to the list of enclosing marked content sections in
  every `LTComponent`, as the `mcstack` attribute.
- Bounding boxes of rotated glyphs are the actual bounding box.

Probably more... but you didn't use any of that stuff anyway, you just
wanted to get `LTTextBoxes` to feed to your hallucination factories.

## Reference

::: playa.miner
