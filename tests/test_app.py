import pytest

from app import create_app
from app.store import SIZE, MemoryStore


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("COOLDOWN_SECONDS", "2")
    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    return create_app(MemoryStore()).test_client()


def test_home(client):
    r = client.get("/")
    assert r.status_code == 200 and b"PIXEL" in r.data


def test_board_starts_blank(client):
    data = client.get("/api/board").get_json()
    assert data["version"] == 0 and data["pixels"] == "0" * SIZE


def test_place_pixel_and_poll(client):
    r = client.post("/api/pixel", json={"x": 3, "y": 1, "c": 13})
    assert r.status_code == 200
    data = client.get("/api/board").get_json()
    assert data["pixels"][1 * 64 + 3] == "d"
    # Polling with the current version returns 204 (nothing new).
    assert client.get(f"/api/board?since={data['version']}").status_code == 204


def test_cooldown(client):
    client.post("/api/pixel", json={"x": 0, "y": 0, "c": 1})
    r = client.post("/api/pixel", json={"x": 1, "y": 0, "c": 1})
    assert r.status_code == 429 and r.get_json()["retry_in"] >= 1


def test_cooldown_is_per_client(client):
    client.post("/api/pixel", json={"x": 0, "y": 0, "c": 1}, headers={"X-Real-IP": "1.1.1.1"})
    r = client.post("/api/pixel", json={"x": 0, "y": 0, "c": 1}, headers={"X-Real-IP": "2.2.2.2"})
    assert r.status_code == 200


@pytest.mark.parametrize("body", [{}, {"x": 64, "y": 0, "c": 0}, {"x": 0, "y": 0, "c": 16}, {"x": "a", "y": 0, "c": 0}])
def test_rejects_bad_input(client, body):
    assert client.post("/api/pixel", json=body).status_code == 400


def test_served_by_header(client):
    assert client.get("/healthz").headers["X-Served-By"]


def test_reset_requires_token(client):
    assert client.post("/api/reset").status_code == 403
    client.post("/api/pixel", json={"x": 0, "y": 0, "c": 5})
    assert client.post("/api/reset", headers={"X-Admin-Token": "secret"}).status_code == 200
    assert client.get("/api/board").get_json()["pixels"][0] == "0"


def test_stats(client):
    client.post("/api/pixel", json={"x": 0, "y": 0, "c": 5})
    assert client.get("/api/stats").get_json()["pixels_placed"] == 1
