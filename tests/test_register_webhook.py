"""Tests for WebEx webhook self-registration (WebEx API mocked)."""

from __future__ import annotations

from packages.webex_bot import register_webhook as rw


class _Resp:
    def __init__(self, payload=None, status=200):
        self._payload = payload or {}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, existing=None):
        self.existing = existing or []
        self.deleted: list[str] = []
        self.created: list[dict] = []
        self._next_id = 0

    def get(self, url, headers=None):
        return _Resp({"items": self.existing})

    def delete(self, url, headers=None):
        self.deleted.append(url.rsplit("/", 1)[-1])
        return _Resp({}, status=204)

    def post(self, url, headers=None, json=None):
        self._next_id += 1
        wid = f"wh{self._next_id}"
        self.created.append({"id": wid, **json})
        return _Resp({"id": wid})


def test_delete_only_miga_prefixed():
    client = _FakeClient(
        existing=[
            {"id": "a", "name": "MIGA-messages-created"},
            {"id": "b", "name": "SomeOtherWebhook"},
            {"id": "c", "name": "MIGA-attachmentActions-created"},
        ]
    )
    deleted = rw.delete_miga_webhooks(client, "tok")
    assert deleted == ["a", "c"]  # 'b' (non-MIGA) untouched


def test_create_both_resources_at_target():
    client = _FakeClient()
    ids = rw.create_webhooks(client, "tok", "https://x.ngrok-free.app/webhooks/webex")
    assert len(ids) == 2
    res = {(c["resource"], c["event"]) for c in client.created}
    assert res == {("messages", "created"), ("attachmentActions", "created")}
    assert all(c["targetUrl"] == "https://x.ngrok-free.app/webhooks/webex" for c in client.created)


def test_register_deletes_then_creates(monkeypatch):
    client = _FakeClient(existing=[{"id": "old", "name": "MIGA-messages-created"}])
    ids = rw.register("tok", "https://x.ngrok-free.app/", client=client)
    assert client.deleted == ["old"]
    assert len(ids) == 2


def test_main_requires_env(monkeypatch):
    monkeypatch.delenv("WEBEX_BOT_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("WEBEX_PUBLIC_URL", raising=False)
    assert rw.main() == 1
