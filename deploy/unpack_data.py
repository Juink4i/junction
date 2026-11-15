"""Build time: open deploy/data.enc into data/raw/, unless the Valio Aimo files are already there.

data.enc is a gzipped tar of data/raw/, encrypted with Fernet. The key comes from the DATA_KEY
build secret (/run/secrets/DATA_KEY), so the hosted Space's public files never hold readable
event data. Made by deploy/publish_space.py.
"""

import io
import os
import sys
import tarfile
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
BLOB = ROOT / "deploy" / "data.enc"
KEY = Path(os.environ.get("DATA_KEY_FILE", "/run/secrets/DATA_KEY"))  # build secret
PRODUCTS = "valio_aimo_junction26_product_data.json"

if (RAW / PRODUCTS).exists():
    sys.exit(0)
if not BLOB.exists() or not KEY.exists():
    sys.exit(f"No {RAW / PRODUCTS}, and no {BLOB.name} with a DATA_KEY build secret to open it.")
plain = Fernet(KEY.read_text().strip().encode()).decrypt(BLOB.read_bytes())
RAW.mkdir(parents=True, exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tar:
    tar.extractall(RAW, filter="data")
BLOB.unlink()
print(f"Opened {len(list(RAW.iterdir()))} Valio Aimo files into {RAW}")
