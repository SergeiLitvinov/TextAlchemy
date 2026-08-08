"""Тесты core.io — единый набор утилит (заменил дубли в core/file_utils и organize/utils)."""
from __future__ import annotations

import os
import zipfile

import pytest

from textalchemy.core.io import (
    ArchiveSafetyError,
    atomic_copy,
    atomic_write_bytes,
    atomic_write_text,
    check_archive_safety,
    compute_hash,
    create_zip_archive,
    ensure_dir,
    ensure_folder,
    find_duplicates_by_paths,
    find_duplicates_in_folder,
    get_file_info,
    list_files,
    progress_bar,
    read_text_file,
    sanitize_filename,
    sanitize_path,
    validate_pdf,
    write_text_file,
)


class TestComputeHash:
    def test_sha256(self, tmp_path):
        f = tmp_path / "f.bin"
        f.write_bytes(b"hello")
        h = compute_hash(f, algorithm="sha256")
        assert len(h) == 64

    def test_md5(self, tmp_path):
        f = tmp_path / "f.bin"
        f.write_bytes(b"hello")
        h = compute_hash(f, algorithm="md5")
        assert len(h) == 32

    def test_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            compute_hash(tmp_path / "nope")


class TestFindDuplicatesByPaths:
    def test_finds_dups(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_bytes(b"same")
        b.write_bytes(b"same")
        dups = find_duplicates_by_paths([a, b])
        assert len(dups) == 1
        assert dups[0] == {a, b}

    def test_no_dups(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_bytes(b"x")
        b.write_bytes(b"y")
        assert find_duplicates_by_paths([a, b]) == []

    def test_skips_dirs(self, tmp_path):
        d = tmp_path / "sub"
        d.mkdir()
        assert find_duplicates_by_paths([d]) == []

    def test_empty(self):
        assert find_duplicates_by_paths([]) == []


class TestFindDuplicatesInFolder:
    def test_scans_recursively(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        a = tmp_path / "a.txt"
        b = sub / "b.txt"
        a.write_bytes(b"same")
        b.write_bytes(b"same")
        dups = find_duplicates_in_folder(tmp_path)
        assert a in dups
        assert b in dups[a]

    def test_no_dups(self, tmp_path):
        a = tmp_path / "a.txt"
        a.write_bytes(b"unique")
        assert find_duplicates_in_folder(tmp_path) == {}


class TestSanitize:
    def test_filename_default(self):
        assert sanitize_filename("a<b>c") == "a_b_c"
        assert sanitize_filename("<>test<>") == "test"
        assert sanitize_filename("normal") == "normal"

    def test_filename_custom_replacement(self):
        assert sanitize_filename("a<b>c", replacement="-") == "a-b-c"

    def test_path_alias(self):
        # Тот же результат, что и sanitize_filename с дефолтом
        assert sanitize_path("a<b>c") == "a_b_c"


class TestEnsureDirFolder:
    def test_creates(self, tmp_path):
        d = ensure_dir(tmp_path / "deep" / "nested")
        assert d.exists()

    def test_existing(self, tmp_path):
        assert ensure_dir(tmp_path) == tmp_path

    def test_folder_alias(self, tmp_path):
        f = ensure_folder(tmp_path / "x" / "y")
        assert f.exists()
        assert f == tmp_path / "x" / "y"


class TestReadWrite:
    def test_utf8_roundtrip(self, tmp_path):
        f = tmp_path / "t.txt"
        write_text_file(f, "hello")
        assert read_text_file(f) == "hello"

    def test_cp1251_fallback(self, tmp_path):
        f = tmp_path / "cp.txt"
        f.write_bytes("тест".encode("cp1251"))
        assert read_text_file(f) == "тест"

    def test_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_text_file(tmp_path / "nope")


class TestProgressBar:
    def test_format(self):
        s = progress_bar(5, 10, width=10)
        assert s.startswith("[")
        assert "5/10" in s


class TestValidatePdf:
    def test_non_pdf_returns_false(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("not a pdf")
        assert validate_pdf(f) is False

    def test_missing(self, tmp_path):
        assert validate_pdf(tmp_path / "nope") is False


class TestGetFileInfo:
    def test_basic(self, tmp_path):
        f = tmp_path / "a.TXT"
        f.write_text("hi")
        info = get_file_info(f)
        assert info["name"] == "a.TXT"
        assert info["size"] == 2
        assert info["extension"] == ".txt"


class TestListFiles:
    def test_with_extension(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        (tmp_path / "b.md").write_text("y")
        (tmp_path / "c.txt").write_text("z")
        files = list_files(tmp_path, extensions=[".txt"])
        assert {f["name"] for f in files} == {"a.txt", "c.txt"}

    def test_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "a.txt").write_text("x")
        (sub / "b.txt").write_text("y")
        # non-recursive: только прямое содержимое
        files = list_files(tmp_path)
        assert {f["name"] for f in files} == {"a.txt"}
        # recursive: всё дерево
        files = list_files(tmp_path, recursive=True)
        assert {f["name"] for f in files} == {"a.txt", "b.txt"}


class TestCreateZipArchive:
    def test_zip(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("A")
        b.write_text("B")
        out = tmp_path / "out.zip"
        create_zip_archive([a, b], out)
        assert out.is_file()
        with zipfile.ZipFile(out) as zf:
            assert set(zf.namelist()) == {"a.txt", "b.txt"}


class TestCheckArchiveSafety:
    """Защита от zip-бомб, path traversal и переполнения ресурсов."""

    def _zip(self, tmp_path, names, contents=None):
        """Собрать zip из имён записей и (опционально) байт."""
        path = tmp_path / "sample.zip"
        contents = contents or [b"x" * 100] * len(names)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in zip(names, contents):
                zf.writestr(name, data)
        return path

    def test_valid_zip_passes(self, tmp_path):
        p = self._zip(tmp_path, ["word/document.xml", "word/styles.xml"])
        assert check_archive_safety(p) is None

    def test_empty_zip_passes(self, tmp_path):
        p = tmp_path / "empty.zip"
        with zipfile.ZipFile(p, "w"):
            pass
        assert check_archive_safety(p) is None

    def test_path_traversal_rejected(self, tmp_path):
        p = self._zip(tmp_path, ["../evil", "word/document.xml"])
        with pytest.raises(ArchiveSafetyError, match="Path traversal"):
            check_archive_safety(p)

    def test_absolute_path_rejected(self, tmp_path):
        p = self._zip(tmp_path, ["/etc/passwd"])
        with pytest.raises(ArchiveSafetyError, match="Абсолютный путь"):
            check_archive_safety(p)

    def test_drive_letter_rejected(self, tmp_path):
        p = self._zip(tmp_path, ["C:/windows/evil"])
        with pytest.raises(ArchiveSafetyError, match="буквой диска"):
            check_archive_safety(p)

    def test_duplicate_entry_rejected(self, tmp_path):
        p = tmp_path / "dup.zip"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("a.txt", b"one")
            zf.writestr("b.txt", b"two")
        # Дубликат имени в том же архиве (zip-slip / неоднозначность распаковки).
        info = zipfile.ZipInfo("a.txt")
        with zipfile.ZipFile(p, "a") as zf:
            zf.writestr(info, b"three")
        with pytest.raises(ArchiveSafetyError, match="Дубликат"):
            check_archive_safety(p)

    def test_too_many_entries_rejected(self, tmp_path):
        p = self._zip(tmp_path, [f"e{i}.xml" for i in range(5)])
        with pytest.raises(ArchiveSafetyError, match="Слишком много записей"):
            check_archive_safety(p, max_entries=3)

    def test_oversized_entry_rejected(self, tmp_path):
        p = self._zip(tmp_path, ["big.bin"], contents=[b"z" * 1024])
        with pytest.raises(ArchiveSafetyError, match="Запись слишком большая"):
            check_archive_safety(p, max_total_size=512)

    def test_total_size_rejected(self, tmp_path):
        p = self._zip(tmp_path, ["a.bin", "b.bin"], contents=[b"z" * 300] * 2)
        with pytest.raises(ArchiveSafetyError, match="Суммарный размер"):
            check_archive_safety(p, max_total_size=512)

    def test_zip_bomb_ratio_rejected(self, tmp_path):
        p = self._zip(tmp_path, ["bomb.bin"], contents=[b"\x00" * 100_000])
        with pytest.raises(ArchiveSafetyError, match="коэффициент"):
            check_archive_safety(p, max_ratio=10)

    def test_per_entry_compression_ratio_cannot_be_diluted(self, tmp_path):
        p = tmp_path / "mixed.zip"
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("bomb.txt", b"0" * (1024 * 1024))
            zf.writestr("noise.bin", os.urandom(1024 * 1024))

        with pytest.raises(ArchiveSafetyError, match="коэффициент сжатия записи"):
            check_archive_safety(p, max_ratio=10)

    def test_not_a_zip_rejected(self, tmp_path):
        p = tmp_path / "junk.zip"
        p.write_bytes(b"this is not a zip file")
        with pytest.raises(ArchiveSafetyError, match="zip"):
            check_archive_safety(p)


class TestAtomicWrites:
    def test_atomic_write_text_creates_parents(self, tmp_path):
        target = tmp_path / "nested" / "out.txt"
        atomic_write_text(target, "hello", encoding="utf-8")
        assert target.read_text(encoding="utf-8") == "hello"

    def test_atomic_write_text_leaves_no_partials(self, tmp_path):
        target = tmp_path / "out.txt"
        atomic_write_text(target, "one")
        atomic_write_text(target, "two")
        assert target.read_text(encoding="utf-8") == "two"
        leftovers = [p for p in tmp_path.iterdir() if ".partial" in p.name]
        assert leftovers == []

    def test_atomic_write_bytes(self, tmp_path):
        target = tmp_path / "out.bin"
        atomic_write_bytes(target, b"\x00\x01\x02")
        assert target.read_bytes() == b"\x00\x01\x02"

    def test_atomic_write_overwrites_existing(self, tmp_path):
        target = tmp_path / "out.txt"
        target.write_text("old", encoding="utf-8")
        atomic_write_text(target, "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_atomic_copy(self, tmp_path):
        src = tmp_path / "src.txt"
        src.write_text("data", encoding="utf-8")
        dst = tmp_path / "sub" / "dst.txt"
        atomic_copy(src, dst)
        assert dst.read_text(encoding="utf-8") == "data"
        leftovers = [p for p in (tmp_path / "sub").iterdir() if ".partial" in p.name]
        assert leftovers == []


class TestLegacyImports:
    """Старые имена функций продолжают работать через re-export."""

    def test_core_file_utils(self):
        from textalchemy.core import file_utils
        # Функции — это те же объекты, что и в core.io
        assert file_utils.sanitize_filename is sanitize_filename
        assert file_utils.ensure_dir is ensure_dir
        assert file_utils.read_text_file is read_text_file
        assert file_utils.write_text_file is write_text_file
        assert file_utils.find_duplicates is find_duplicates_by_paths
        # compute_file_hash — обёртка из core.hashing
        from textalchemy.core.hashing import compute_file_hash
        assert file_utils.compute_file_hash is compute_file_hash

    def test_organize_utils(self):
        from textalchemy.organize import utils
        assert utils.calculate_file_hash is compute_hash
        assert utils.sanitize_path is sanitize_path
        assert utils.ensure_folder is ensure_folder
        assert utils.find_duplicates is find_duplicates_in_folder
        assert utils.create_zip_archive is create_zip_archive
        assert utils.get_file_info is get_file_info
        assert utils.list_files is list_files
        assert utils.progress_bar is progress_bar
        assert utils.validate_pdf is validate_pdf

