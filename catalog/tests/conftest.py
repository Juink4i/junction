from pathlib import Path

import pytest

from catalog import load

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


@pytest.fixture(scope="session")
def catalog_db(tmp_path_factory) -> Path:
    """Load the real Valio Aimo files once per test run into a throwaway database."""
    if not (RAW / load.PRODUCT_FILE).exists():
        pytest.skip("Valio Aimo files are not in data/raw/")
    db = tmp_path_factory.mktemp("catalog") / "catalog.db"
    load.load(RAW, db)
    return db
