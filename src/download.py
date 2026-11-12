"""Download the Kelmarsh dataset files from Zenodo and unzip the SCADA archive."""

import hashlib
import logging
import zipfile
from collections.abc import Callable
from pathlib import Path

import requests
from tqdm import tqdm

from src.config import load_config

logger = logging.getLogger(__name__)

CHUNK_BYTES = 1 << 20
TIMEOUT_S = 60

Fetcher = Callable[[str, Path], None]


def md5_of(path: Path) -> str:
    """Return the hex MD5 digest of a file, read in chunks."""
    digest = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def needs_download(path: Path, expected_md5: str) -> bool:
    """True unless the file exists and its MD5 matches."""
    return not (path.exists() and md5_of(path) == expected_md5)


def fetch(url: str, dest: Path) -> None:
    """Stream a URL to dest with a progress bar, via a temporary .part file."""
    part = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=TIMEOUT_S) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        with (
            part.open("wb") as f,
            tqdm(total=total, unit="B", unit_scale=True, desc=dest.name) as bar,
        ):
            for chunk in response.iter_content(CHUNK_BYTES):
                f.write(chunk)
                bar.update(len(chunk))
    part.replace(dest)


def ensure_file(
    name: str, url: str, md5: str, raw_dir: Path, fetcher: Fetcher = fetch
) -> bool:
    """Download one file if needed and verify it. Return True if downloaded."""
    dest = raw_dir / name
    if not needs_download(dest, md5):
        logger.info("Skipping %s: already present with correct MD5", name)
        return False
    logger.info("Downloading %s", name)
    fetcher(url, dest)
    actual = md5_of(dest)
    if actual != md5:
        raise ValueError(f"MD5 mismatch for {name}: expected {md5}, got {actual}")
    return True


def is_extracted(archive: Path, target_dir: Path) -> bool:
    """True if every file in the archive already exists under target_dir."""
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.namelist() if not m.endswith("/")]
    return all((target_dir / m).exists() for m in members)


def extract(archive: Path, target_dir: Path) -> bool:
    """Unzip archive into target_dir unless already done. Return True if unzipped."""
    if target_dir.exists() and is_extracted(archive, target_dir):
        logger.info("Skipping unzip: %s already extracted", target_dir)
        return False
    logger.info("Extracting %s into %s", archive.name, target_dir)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(target_dir)
    return True


def main() -> None:
    """Download all configured files and unzip the SCADA archive."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = load_config()
    raw_dir = Path(config["paths"]["raw"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    files = config["downloads"]["files"]
    downloaded = [ensure_file(f["name"], f["url"], f["md5"], raw_dir) for f in files]
    logger.info("Downloaded %d of %d files", sum(downloaded), len(files))
    archive = next(raw_dir / f["name"] for f in files if f["name"].endswith(".zip"))
    extract(archive, raw_dir / config["downloads"]["scada_dir"])


if __name__ == "__main__":
    main()
