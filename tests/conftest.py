import pytest

from relaylab import create_app

HEADERS = {"X-RelayLab-Request": "1"}


@pytest.fixture()
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "relaylab.sqlite3")})


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def inbox(client):
    response = client.post("/api/inboxes", json={"name": "Test inbox"}, headers=HEADERS)
    assert response.status_code == 201
    return response.json
