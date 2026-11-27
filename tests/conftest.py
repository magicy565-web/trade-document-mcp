from pathlib import Path
import pytest
from trade_document.model import Order


@pytest.fixture
def order():
    return Order.model_validate_json(
        (Path(__file__).parents[1] / "fixtures/sample.json").read_bytes()
    )


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_DOC_HOME", str(tmp_path / "store"))
    monkeypatch.delenv("TRADE_DOC_REVIEWERS", raising=False)
