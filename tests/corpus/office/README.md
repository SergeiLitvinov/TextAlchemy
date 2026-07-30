# Office provenance fixtures

`libreoffice-scientific-slides.pptx` is the reproducible source presentation from
`tests.corpus.multiformat`, opened and re-saved by LibreOffice 25.8.6.2 on Windows.
It contains only project-generated content. ZIP timestamps are normalized after
the office-suite roundtrip; the producer metadata and converted WMF media part are
left untouched. `manifest.json` records provenance, size, SHA-256 and structural
expectations.

The fixture is intentionally committed because office-suite serialization cannot
be reproduced in CI without that exact application and version. Source-first PDF,
PPTX and EMF fixtures remain generated during tests and require no office suite.
