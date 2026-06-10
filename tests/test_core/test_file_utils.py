from pathlib import Path

import pytest

from textalchemy.core.file_utils import (
    compute_file_hash,
    ensure_dir,
    find_duplicates,
    read_text_file,
    sanitize_filename,
    write_text_file,
)


class TestSanitizeFilename:
    def test_replaces_special_chars(self):
        assert sanitize_filename("foo<bar>:baz?.txt") == "foo_bar_baz_.txt"

    def test_collapses_replacement(self):
        result = sanitize_filename("a<b>c", replacement="_")
        assert "___" not in result

    def test_strips_leading_trailing_replacement(self):
        assert sanitize_filename("<>test<>") == "test"

    def test_no_change(self):
        assert sanitize_filename("normal.txt") == "normal.txt"

    def test_empty(self):
        assert sanitize_filename("") == ""


class TestComputeFileHash:
    def test_sha256(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello")
        h = compute_file_hash(f, algorithm="sha256")
        assert len(h) == 64

    def test_md5(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello")
        h = compute_file_hash(f, algorithm="md5")
        assert len(h) == 32

    def test_consistent(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"data")
        assert compute_file_hash(f) == compute_file_hash(f)

    def test_no_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            compute_file_hash(tmp_path / "nonexistent")


class TestFindDuplicates:
    def test_finds_duplicates(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("same")
        b.write_text("same")
        dups = find_duplicates([a, b])
        assert len(dups) >= 1
        assert len(dups[0]) == 2

    def test_no_duplicates(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("foo")
        b.write_text("bar")
        dups = find_duplicates([a, b])
        assert dups == []

    def test_skips_directories(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        dups = find_duplicates([d])
        assert dups == []

    def test_empty_list(self):
        assert find_duplicates([]) == []


class TestEnsureDir:
    def test_creates_directory(self, tmp_path):
        d = tmp_path / "new" / "deep" / "dir"
        result = ensure_dir(d)
        assert result == d
        assert d.exists()

    def test_existing_directory(self, tmp_path):
        result = ensure_dir(tmp_path)
        assert result == tmp_path


class TestReadWriteText:
    def test_write_and_read_utf8(self, tmp_path):
        f = tmp_path / "test.txt"
        write_text_file(f, "hello world")
        assert read_text_file(f) == "hello world"

    def test_read_nonexistent(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_text_file(tmp_path / "nonexistent")

    def test_read_cp1251(self, tmp_path):
        f = tmp_path / "cp1251.txt"
        f.write_bytes("тест".encode("cp1251"))
        assert read_text_file(f) == "тест"
