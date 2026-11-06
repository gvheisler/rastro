"""Download the amendment files from Portal da Transparência (CGU).

Overwrites the CSVs in data/raw and prints the table rows for data/README.md.
"""

import argparse
import hashlib
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

URL = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
USER_AGENT = "rastro/0.1 (+https://github.com/gvheisler/rastro)"
FILES = (
    "EmendasParlamentares.csv",
    "EmendasParlamentares_Convenios.csv",
    "EmendasParlamentares_PorFavorecido.csv",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_rows(path: Path) -> int:
    """Data rows, excluding the header."""
    with path.open("rb") as f:
        return sum(chunk.count(b"\n") for chunk in iter(lambda: f.read(1 << 20), b"")) - 1


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as out:
        shutil.copyfileobj(response, out)


def main(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "emendas.zip"
        download(URL, archive)
        with zipfile.ZipFile(archive) as zf:
            if (bad := zf.testzip()) is not None:
                raise SystemExit(f"corrupt member in zip: {bad}")
            missing = set(FILES) - set(zf.namelist())
            if missing:
                raise SystemExit(f"files missing from zip: {sorted(missing)}")
            for name in FILES:
                with zf.open(name) as src, (dest / name).open("wb") as out:
                    shutil.copyfileobj(src, out)

    for name in FILES:
        path = dest / name
        size_mb = path.stat().st_size / 1e6
        print(f"| `{name}` | {count_rows(path):,} | {size_mb:.1f} MB | `{sha256(path)}` |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, default=Path("data/raw"))
    main(parser.parse_args().dest)
