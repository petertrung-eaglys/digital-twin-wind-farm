"""Tests for the download helpers (no network access)."""

import hashlib
import zipfile
from pathlib import Path

import pytest

from src.download import ensure_file, extract, md5_of, needs_download

CONTENT = b"kelmarsh"
CONTENT_MD5 = hashlib.md5(CONTENT).hexdigest()


def write_fetcher(content: bytes, calls: list[str]):
    """Return a fake fetcher that records URLs and writes fixed content."""

    def fetcher(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(content)

    return fetcher


def test_md5_of_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(CONTENT)

    assert md5_of(path) == CONTENT_MD5


def test_needs_download_when_file_missing(tmp_path: Path) -> None:
    assert needs_download(tmp_path / "missing.csv", CONTENT_MD5)


def test_needs_download_when_md5_differs(tmp_path: Path) -> None:
    path = tmp_path / "f.csv"
    path.write_bytes(b"corrupted")

    assert needs_download(path, CONTENT_MD5)


def test_no_download_needed_when_md5_matches(tmp_path: Path) -> None:
    path = tmp_path / "f.csv"
    path.write_bytes(CONTENT)

    assert not needs_download(path, CONTENT_MD5)


def test_ensure_file_downloads_once_then_skips(tmp_path: Path) -> None:
    calls: list[str] = []
    fetcher = write_fetcher(CONTENT, calls)

    first = ensure_file("f.csv", "http://x/f", CONTENT_MD5, tmp_path, fetcher)
    second = ensure_file("f.csv", "http://x/f", CONTENT_MD5, tmp_path, fetcher)

    assert (first, second, calls) == (True, False, ["http://x/f"])


def test_ensure_file_raises_on_md5_mismatch(tmp_path: Path) -> None:
    fetcher = write_fetcher(b"wrong", [])

    with pytest.raises(ValueError, match="MD5 mismatch"):
        ensure_file("f.csv", "http://x/f", CONTENT_MD5, tmp_path, fetcher)


def make_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("sub/a.csv", "a")
        zf.writestr("b.csv", "b")
    return path


def test_extract_unzips_all_members(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "x.zip")
    target = tmp_path / "out"

    assert extract(archive, target)
    assert (target / "sub/a.csv").read_text() == "a"


def test_extract_skips_when_already_extracted(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "x.zip")
    target = tmp_path / "out"
    extract(archive, target)

    assert not extract(archive, target)
