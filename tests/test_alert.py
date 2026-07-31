from tech_news_purifier.alert import _sanitize, send_alert


def test_alert_sanitizes_credentials() -> None:
    value = _sanitize("Authorization: Bearer abc.def token=secret key=value")
    assert "abc.def" not in value
    assert "secret" not in value
    assert "value" not in value


def test_alert_posts_json(monkeypatch) -> None:
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, *, json, timeout):
        captured.update(url=url, payload=json, timeout=timeout)
        return Response()

    monkeypatch.setattr("tech_news_purifier.alert.httpx.post", fake_post)
    send_alert("https://alerts.example/hook", {"result": "failed"})
    assert captured["url"] == "https://alerts.example/hook"
    assert captured["payload"] == {"result": "failed"}
