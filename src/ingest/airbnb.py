"""Download an Inside Airbnb city snapshot to data/raw/."""
import sys
from pathlib import Path
import requests

RAW_DIR = Path("data/raw")


def download(url: str, out_name: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / out_name

    if out_path.exists():
        print(f"{out_path} already exists, skipping")
        return out_path

    print(f"Downloading {url}")
    # stream=True avoids loading the whole file into memory
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    print(f"Saved {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    return out_path


if __name__ == "__main__":
    url = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else "listings.csv.gz"
    download(url, name)