import asyncio
from pathlib import Path

import pytest

from textalchemy.core.artifacts import ArtifactLimitError, ArtifactWorkspace


class _Upload:
    def __init__(self, chunks: list[bytes], filename: str = "upload.bin") -> None:
        self.filename = filename
        self._chunks = iter(chunks)

    async def read(self, _size: int) -> bytes:
        return next(self._chunks, b"")


def test_workspace_sanitizes_names_and_cleans_up(tmp_path):
    workspace = ArtifactWorkspace(parent=tmp_path)
    root = workspace.path

    artifact = workspace.write_bytes(r"..\..\outside.txt", b"safe")

    assert artifact == root / "outside.txt"
    assert artifact.read_bytes() == b"safe"
    workspace.cleanup()
    workspace.cleanup()
    assert not root.exists()


def test_workspace_streams_upload_atomically(tmp_path):
    with ArtifactWorkspace(parent=tmp_path, max_bytes=8) as workspace:
        artifact = asyncio.run(workspace.write_upload(_Upload([b"abc", b"def"]), "/absolute/document.pdf"))
        assert artifact == workspace.path / "document.pdf"
        assert artifact.read_bytes() == b"abcdef"
        assert not list(workspace.path.glob("*.partial"))


def test_workspace_rejects_oversized_upload_without_partial_file(tmp_path):
    workspace = ArtifactWorkspace(parent=tmp_path, max_bytes=5)

    with pytest.raises(ArtifactLimitError):
        asyncio.run(workspace.write_upload(_Upload([b"1234", b"56"]), "large.bin"))

    assert list(workspace.path.iterdir()) == []
    workspace.cleanup()


def test_workspace_rejects_external_and_oversized_generated_artifacts(tmp_path):
    with ArtifactWorkspace(parent=tmp_path, max_bytes=5) as workspace:
        outside = tmp_path / "outside.bin"
        outside.write_bytes(b"x")
        with pytest.raises(ValueError, match="outside"):
            workspace.validate_artifact(outside)

        generated = workspace.artifact_path("generated.bin")
        generated.write_bytes(b"123456")
        with pytest.raises(ArtifactLimitError):
            workspace.validate_artifact(generated)


def test_workspace_rejects_access_after_cleanup(tmp_path):
    workspace = ArtifactWorkspace(parent=tmp_path)
    workspace.cleanup()

    with pytest.raises(RuntimeError, match="closed"):
        workspace.artifact_path("late.txt")


def test_workspace_path_is_always_inside_root(tmp_path):
    with ArtifactWorkspace(parent=tmp_path) as workspace:
        path = workspace.artifact_path("folder/file.txt")
        assert path.parent == workspace.path
        assert workspace.path in Path(path).resolve().parents
