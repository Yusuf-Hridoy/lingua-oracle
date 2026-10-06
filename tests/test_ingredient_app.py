"""The ingredient check inside the web application.

The worker is driven with a stub client: no network, and the test can say
exactly what the app returns. The comparison itself is tested in
test_ingredient_check.py; this is about the run, its progress and its page.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from lingua_oracle.api import ingredients as ing
from lingua_oracle.api.app import app
from lingua_oracle.ingredients.client import AppUnavailable, Ingredient


class StubClient:
    """Stands in for the ExactSDS client. Returns fixed, fictional data."""

    products = {
        1: [Ingredient(cas="67-64-1", name="<substance A>",
                       h_codes=["H225", "H319", "H335"], concentration="50")],
        2: [Ingredient(cas="67-64-1", name="<substance A>",
                       h_codes=["H225", "H319", "H336", "EUH066"],
                       concentration="10"),
            Ingredient(cas="7732-18-5", name="<substance B>", h_codes=[],
                       concentration="40")],
    }

    def login(self) -> None:
        pass

    def walk_product_ids(self):
        yield from sorted(self.products)

    def ingredients(self, product_id):
        return self.products.get(product_id, [])

    def substance_source(self, cas):
        return "stub"

    def close(self) -> None:
        pass


class BrokenClient(StubClient):
    def login(self) -> None:
        raise AppUnavailable("EXACTSDS_URL is not set in .env")


def _finished(progress, timeout: float = 20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if progress.state in ("done", "failed"):
            return progress
        time.sleep(0.02)
    raise AssertionError(f"run never finished: {progress.state}")


@pytest.fixture
def runs_here(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, "runs_dir", lambda: tmp_path)
    return tmp_path


# -- the run -------------------------------------------------------------------


def test_a_library_run_reads_every_product_and_saves_one_file(runs_here):
    progress = _finished(ing.start("library", None, client_factory=StubClient))
    assert progress.state == "done"
    assert progress.products_read == 2
    assert progress.substances_found == 2
    saved = list(runs_here.glob("*.json"))
    assert len(saved) == 1
    data = json.loads(saved[0].read_text())
    assert data["counts"]["products"] == 2
    assert data["counts"]["substances"] == 2


def test_a_single_product_run_reads_only_that_product(runs_here):
    progress = _finished(ing.start("product", 1, client_factory=StubClient))
    assert progress.products_read == 1
    data = json.loads(next(runs_here.glob("*.json")).read_text())
    assert data["counts"]["products"] == 1
    assert [s["cas"] for s in data["substances"]] == ["67-64-1"]


def test_the_run_groups_the_two_products_into_one_substance(runs_here):
    _finished(ing.start("library", None, client_factory=StubClient))
    data = json.loads(next(runs_here.glob("*.json")).read_text())
    substance = next(s for s in data["substances"] if s["cas"] == "67-64-1")
    assert substance["uses_checked"] == 2
    assert substance["uses_under_classified"] == 1      # the H335 product
    assert substance["missing_code_counts"] == {"EUH066": 1, "H336": 1}
    assert substance["distinct_code_sets"] == 2
    assert substance["inconsistent"] is True
    assert substance["affected_products"] == [1]


def test_a_failure_is_reported_not_swallowed(runs_here):
    progress = _finished(ing.start("library", None, client_factory=BrokenClient))
    assert progress.state == "failed"
    assert "EXACTSDS_URL" in progress.message
    assert list(runs_here.glob("*.json")) == []


def test_progress_is_readable_while_the_run_is_going(runs_here):
    progress = ing.start("library", None, client_factory=StubClient)
    assert progress.as_dict()["state"] in ("reading", "grouping", "done")
    _finished(progress)
    assert progress.as_dict()["run_file"]


# -- the pages -----------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_the_run_page_offers_both_scopes(client):
    body = client.get("/ingredients").text
    assert 'name="scope" value="product"' in body
    assert 'name="scope" value="library"' in body
    assert "Run check" in body


def test_a_product_run_without_an_id_explains_itself(client):
    body = client.post("/ingredients/run",
                       data={"scope": "product", "product_id": ""}).text
    assert "Give a product ID" in body
    assert "Run check" in body            # back on the form, not a dead end


def test_a_started_run_shows_progress(client, runs_here, monkeypatch):
    monkeypatch.setattr(ing, "ExactSdsClient", StubClient, raising=False)
    import lingua_oracle.ingredients.client as client_module

    monkeypatch.setattr(client_module, "ExactSdsClient", StubClient)
    body = client.post("/ingredients/run",
                       data={"scope": "product", "product_id": "1"}).text
    assert "Reading ingredients" in body
    assert "products read" in body


def test_the_status_endpoint_answers_for_a_known_run(client, runs_here):
    progress = _finished(ing.start("library", None, client_factory=StubClient))
    body = client.get(f"/ingredients/runs/{progress.id}/status").json()
    assert body["state"] == "done"
    assert body["products_read"] == 2


def test_an_unknown_run_is_a_404(client):
    assert client.get("/ingredients/runs/nope/status").status_code == 404
    assert client.get("/ingredients/runs/nope").status_code == 404


def test_a_saved_run_renders_as_a_report(client, runs_here):
    progress = _finished(ing.start("library", None, client_factory=StubClient))
    body = client.get(f"/ingredients/runs/{progress.run_file}").text
    assert "Ingredient check" in body
    assert "Under-classified" in body
    assert "Annex VI requires" in body
    assert "67-64-1" in body
    assert "affected product" in body
    assert "Technical details" in body


def test_the_report_page_carries_the_navigation(client, runs_here):
    progress = _finished(ing.start("library", None, client_factory=StubClient))
    body = client.get(f"/ingredients/runs/{progress.run_file}").text
    assert 'href="/ingredients"' in body
    assert 'href="/history"' in body


def test_runs_appear_in_history(client, runs_here):
    _finished(ing.start("library", None, client_factory=StubClient))
    rows = ing.recent_runs()
    assert rows and rows[0]["kind"] == "ingredients"
    assert "substances" in rows[0]["file_name"]
