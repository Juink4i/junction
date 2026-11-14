from pathlib import Path
from types import SimpleNamespace

import pytest

from catalog import api, load
from catalog.tests.fake_valio import FakeClock, FakeValio
from catalog.valio_client import ValioClient

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


class NoNetwork:
    """Stands in for the API client in tests that must not price anything."""

    def offers(self, *a, **k):
        raise AssertionError("this test must not call the Valio Aimo API")

    def cached_price(self, *a, **k):
        return None


@pytest.fixture
def catalog(catalog_db, overrides_file):
    """The catalog API pointed at the test database, an empty overrides file and no API access."""
    api.configure(db_path=catalog_db, overrides_path=overrides_file, client=NoNetwork())
    yield api
    api.configure()


def _priced(catalog_db, overrides_file, ttl):
    fake, clock = FakeValio(), FakeClock()
    client = ValioClient(api_key="test-key", transport=fake.transport(), clock=clock, ttl_seconds=ttl)
    api.configure(db_path=catalog_db, overrides_path=overrides_file, client=client)
    return SimpleNamespace(fake=fake, clock=clock, overrides=overrides_file)


@pytest.fixture
def priced(catalog_db, overrides_file):
    """The catalog API with a fake Valio Aimo API that replays recorded responses."""
    yield _priced(catalog_db, overrides_file, ttl=300)
    api.configure()


@pytest.fixture
def priced_long_cache(catalog_db, overrides_file):
    yield _priced(catalog_db, overrides_file, ttl=10**9)
    api.configure()
