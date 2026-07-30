# Document quality corpus

The corpus is generated from source instead of storing opaque binary fixtures. Run:

```powershell
uv run python -m tests.corpus.scientific_report
```

The primary `scientific_report` fixture covers portrait and landscape sections,
named styles, numbering, headers and a page-number footer, hyperlinks, merged
tables, raster and SVG images, native OMML, and a footnote. Archive timestamps and
document metadata are fixed so identical dependencies produce identical bytes.

Structural expectations live in `scientific_report.golden.json`. Visual checks use
tolerant page occupancy bounds because font rasterisation differs across operating
systems.
