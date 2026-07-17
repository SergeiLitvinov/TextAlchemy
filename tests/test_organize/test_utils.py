from pathlib import Path

from textalchemy.organize.utils import (
    calculate_file_hash,
    create_zip_archive,
    ensure_folder,
    find_duplicates,
    get_file_info,
    list_files,
    progress_bar,
    sanitize_path,
    validate_pdf,
)


def test_progress_bar():
    bar = progress_bar(5, 10)
    assert isinstance(bar, str)
    assert "5/10" in bar


def test_progress_bar_zero():
    bar = progress_bar(0, 0)
    assert isinstance(bar, str)


def test_sanitize_path():
    result = sanitize_path("test<file>:name?.pdf")
    assert "<" not in result
    assert ">" not in result
    assert "?" not in result


def test_sanitize_path_empty():
    assert sanitize_path("") == ""


def test_ensure_folder(tmp_path):
    folder = tmp_path / "new_folder"
    result = ensure_folder(folder)
    assert result == folder
    assert folder.exists()


def test_get_file_info(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello", encoding="utf-8")
    info = get_file_info(f)
    assert info["name"] == "test.txt"
    assert info["size"] == 5


def test_get_file_info_no_file():
    import pytest
    with pytest.raises(FileNotFoundError):
        get_file_info(Path("nonexistent.txt"))


def test_list_files(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.pdf").write_text("b", encoding="utf-8")
    files = list_files(tmp_path)
    assert len(files) == 2


def test_list_files_empty(tmp_path):
    assert list_files(tmp_path) == []


def test_list_files_nonexistent():
    assert list_files(Path("nonexistent")) == []


def test_calculate_file_hash(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello", encoding="utf-8")
    h = calculate_file_hash(f)
    assert len(h) in (32, 64)  # md5 or sha256


def test_calculate_file_hash_no_file():
    import pytest
    with pytest.raises(FileNotFoundError):
        calculate_file_hash(Path("nonexistent"))


def test_find_duplicates(tmp_path):
    (tmp_path / "a.txt").write_text("same content", encoding="utf-8")
    (tmp_path / "b.txt").write_text("same content", encoding="utf-8")
    dups = find_duplicates(tmp_path)
    assert len(dups) >= 1


def test_find_duplicates_empty(tmp_path):
    assert isinstance(find_duplicates(tmp_path), (dict, list))


def test_validate_pdf(tmp_path):
    f = tmp_path / "test.pdf"
    f.write_text("not a real pdf", encoding="utf-8")
    assert validate_pdf(f) is False


def test_validate_pdf_no_file():
    assert validate_pdf(Path("nonexistent.pdf")) is False


def test_create_zip_archive(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("content", encoding="utf-8")
    zip_path = tmp_path / "archive.zip"
    result = create_zip_archive([f], zip_path)
    assert result == zip_path
    assert zip_path.exists()



