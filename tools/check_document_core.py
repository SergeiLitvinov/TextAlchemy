"""Verify an installed document wheel with no application or format backends."""

import argparse
import subprocess
import tempfile
from pathlib import Path

PROBE = """
import importlib.util
from importlib.metadata import distribution
from pathlib import Path
import opendoc as core

for name in ('textalchemy', 'fastapi', 'docx', 'pptx', 'fitz', 'lxml'):
    assert importlib.util.find_spec(name) is None, name
dist = distribution('opendoc')
assert all('extra ==' in requirement for requirement in dist.requires or []), dist.requires
assert Path(core.__file__).is_relative_to(Path(__import__('sys').prefix)), core.__file__
paragraph = core.Paragraph(content=[core.TextRun('Independent document')],
                           properties={'editor_extension': {'revision': 7}})
document = core.DocumentModel(sections=[core.Section(blocks=[paragraph])], metadata={'editor': {'session': 'test'}})
document.add_resource(core.Resource(id='asset', kind=core.ResourceKind.ATTACHMENT,
                                  media_type='application/octet-stream', data=b'embedded'))
before = core.inspect_document_model(document)
path = core.save_document(document, 'document.json')
restored = core.load_document(path)
assert restored.validate() == []
assert restored.sections[0].blocks[0].properties['editor_extension'] == {'revision': 7}
assert restored.metadata == document.metadata
assert restored.resources['asset'].data == b'embedded'
after = core.inspect_document_model(restored)
comparison = core.compare_inspections(before, after)
assert before.metrics['paragraphs'] == 1
assert comparison.retention['characters']['ratio'] == 1
report = core.ConversionReport(Path('result.json'))
core.ObjectLossPolicy(max_lost_objects=0).evaluate(report, comparison)
assert report.success, report.to_dict()
print('Independent wheel: model, resources, extensions, persistence and comparison OK')
"""


def verify(python: str) -> None:
    with tempfile.TemporaryDirectory(prefix="document-core-probe-") as directory:
        # Resolving a venv symlink on Unix selects the base interpreter and loses installed wheels.
        subprocess.run([str(Path(python).absolute()), "-I", "-c", PROBE], cwd=directory, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, help="Python in an empty environment with only the core wheel installed")
    verify(parser.parse_args().python)
