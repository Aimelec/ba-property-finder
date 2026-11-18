"""The polite HTTP client (sources/client.py): retries, refusals, stop, request log. No network."""
import pytest

from depa_app.sources import client as client_mod
from depa_app.sources.client import Blocked, Client, Stopped


class FakeResponse:
    def __init__(self, status=200, text="<html>listing</html>"):
        self.status_code, self.text = status, text


@pytest.fixture(autouse=True)
def request_log(tmp_path, monkeypatch):
    log = tmp_path / "pedidos.csv"
    monkeypatch.setattr(client_mod, "REQ_LOG", log)      # never write to the real data/ folder
    return log


def make(responses, **opts):
    """Client whose session answers with `responses` in order (an exception instance is raised)."""
    c = Client(pause=(0, 0), block_waits=(0, 0), log=lambda m: c.messages.append(m), **opts)
    c.messages = []
    answers = iter(responses)

    def get(url, timeout):
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a
    c.s.get = get
    return c


def test_page_is_returned_and_logged(request_log):
    c = make([FakeResponse(200, "<html>ok</html>")])
    assert c.get("https://site.example/p1") == "<html>ok</html>"
    header, line = request_log.read_text(encoding="utf-8").splitlines()
    assert header.startswith("hora,sitio,resultado") and ",site.example,ok,200," in line


def test_missing_page_is_none():
    assert make([FakeResponse(404, "")]).get("https://site.example/x") is None


def test_refused_then_ok_retries_after_waiting():
    c = make([FakeResponse(403, "Just a moment..."), FakeResponse(200, "<html>ok</html>")])
    assert c.get("https://site.example/p1") == "<html>ok</html>"
    assert any("HTTP 403" in m for m in c.messages)


def test_a_challenge_page_with_status_200_counts_as_refused():
    c = make([FakeResponse(200, "<title>Just a moment...</title>"), FakeResponse(200, "<html>ok</html>")])
    assert c.get("https://site.example/p1") == "<html>ok</html>"


def test_gives_up_after_all_waits():
    c = make([FakeResponse(429, "")] * 3)
    with pytest.raises(Blocked):
        c.get("https://site.example/p1")


def test_network_errors_are_retried():
    import requests
    c = make([requests.ConnectionError("down"), FakeResponse(200, "<html>ok</html>")])
    assert c.get("https://site.example/p1") == "<html>ok</html>"


def test_stop_interrupts_before_the_request():
    c = make([FakeResponse(200)], should_stop=lambda: True)
    with pytest.raises(Stopped):
        c.get("https://site.example/p1")


def test_an_alternative_fetcher_is_used_when_given():
    class Fetcher:
        def __init__(self):
            self.urls = []

        def fetch(self, url, should_stop):
            self.urls.append(url)
            return "<html>from the browser</html>"
    f = Fetcher()
    c = Client(pause=(0, 0), browser=f, log=lambda m: None)
    assert c.get("https://site.example/p1") == "<html>from the browser</html>" and f.urls == ["https://site.example/p1"]


def test_batch_pause_is_announced_every_n_pages():
    c = make([FakeResponse(200)] * 3, batch=(2, 0))
    for _ in range(3):
        c.get("https://site.example/p")
    assert sum("Pausing" in m for m in c.messages) == 1
