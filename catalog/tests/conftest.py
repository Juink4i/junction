from pathlib import Path

import pytest

from catalog import api, load

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


@pytest.fixture(scope="session")
def catalog_db(tmp_path_factory) -> Path:
    """Load the real Valio Aimo files once per test run into a throwaway database."""
    if not (RAW / load.PRODUCT_FILE).exists():
        pytest.skip("Valio Aimo files are not in data/raw/")
    db = tmp_path_factory.mktemp("catalog") / "catalog.db"
    load.load(RAW, db)
    return db


@pytest.fixture
def overrides_file(tmp_path) -> Path:
    path = tmp_path / "overrides.json"
    path.write_text('{"offers": {}, "products": {}}', encoding="utf-8")
    return path


@pytest.fixture
def catalog(catalog_db, overrides_file):
    """The catalog API pointed at the test database, an empty overrides file and no API client."""
    api.configure(db_path=catalog_db, overrides_path=overrides_file, client=None)
    yield api
    api.configure()
