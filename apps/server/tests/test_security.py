"""Write modes: open, token, and off. Reads are open in every mode."""

import os
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from typer.testing import CliRunner

from openpipeline.api import create_app
from openpipeline.cli import app as cli_app
from openpipeline.proposals import FileChange, Proposal, ProposalStore
from openpipeline.security import (
    BearerTokenMiddleware,
    WriteGuard,
    browser_url,
    is_loopback_host,
    resolve_write_mode,
    settings_from_env,
    split_host_header,
)

LOCAL = "http://127.0.0.1:8484"
TOKEN = "s3cret-token"
JSON = {"Content-Type": "application/json"}
runner = CliRunner()


def _client(project_dir: Path, mode: Any, fake: Any = None, **kw: Any) -> TestClient:
    kw.setdefault("port", 8484)
    api = create_app(
        project_dir,
        serve_ui=False,
        ai_client=fake,
        writes=mode,
        write_token=TOKEN if mode == "token" else None,
        **kw,
    )
    return TestClient(api, base_url=LOCAL)


def _proposal(project_dir: Path) -> str:
    changes = [FileChange(path="models/marts/revenue.sql", content="select 1 as r")]
    return ProposalStore(project_dir).create(Proposal(title="t", changes=changes)).id


def _writes(pid: str) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Every state-changing or paid endpoint: method, path, JSON body."""
    return [
        ("PUT", "/api/models/customers/docs", {"description": "Changed by a test."}),
        ("POST", f"/api/proposals/{pid}", {"status": "accepted"}),
        ("POST", f"/api/proposals/{pid}/comments", {"text": "hello"}),
        ("POST", "/api/models/customers/ai-explanation", None),
    ]


def _send(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None, **kw: Any
) -> Any:
    kw.setdefault("headers", {**JSON})
    return client.request(method, path, json=body, **kw)


def _bearer(token: str = TOKEN) -> dict[str, str]:
    return {**JSON, "Authorization": f"Bearer {token}"}


def _yaml_snapshot(project_dir: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in project_dir.rglob("*.yml")}


def test_every_write_route_is_covered_by_these_tests(project_dir: Path) -> None:
    """If someone adds a write endpoint, this fails until it is added to `_writes`."""
    api = create_app(project_dir, serve_ui=False)
    found = {
        (m, r.path.replace("{name}", "customers").replace("{proposal_id}", "PID"))
        for r in api.routes
        if isinstance(r, APIRoute) and r.path.startswith("/api")
        for m in r.methods
        if m not in {"GET", "HEAD", "OPTIONS"}
    }
    assert found == {(m, p) for m, p, _ in _writes("PID")}


# --- off ---------------------------------------------------------------------------


def test_off_refuses_every_write(project_dir: Path, fake_ai: Any) -> None:
    client = _client(project_dir, "off", fake_ai)
    before = _yaml_snapshot(project_dir)
    for method, path, body in _writes(_proposal(project_dir)):
        for headers in (JSON, _bearer()):
            r = _send(client, method, path, body, headers=headers)
            assert r.status_code == 403, (method, path)
            assert "read-only" in r.json()["detail"]
    assert _yaml_snapshot(project_dir) == before
    assert ProposalStore(project_dir).list()[0].status == "pending"
    assert fake_ai.calls == []


def test_off_still_reads(project_dir: Path) -> None:
    client = _client(project_dir, "off")
    assert client.get("/api/project").status_code == 200
    assert client.get("/api/proposals").status_code == 200


# --- token -------------------------------------------------------------------------


def test_token_missing_is_401(project_dir: Path, fake_ai: Any) -> None:
    client = _client(project_dir, "token", fake_ai)
    before = _yaml_snapshot(project_dir)
    for method, path, body in _writes(_proposal(project_dir)):
        r = _send(client, method, path, body)
        assert r.status_code == 401, (method, path)
        assert "token" in r.json()["detail"]
        assert r.headers["www-authenticate"].startswith("Bearer")
    assert _yaml_snapshot(project_dir) == before
    assert ProposalStore(project_dir).list()[0].status == "pending"
    assert fake_ai.calls == []


def test_token_wrong_is_401(project_dir: Path) -> None:
    client = _client(project_dir, "token")
    for method, path, body in _writes(_proposal(project_dir)):
        for headers in (
            _bearer("nope"),
            _bearer(TOKEN + "x"),
            {**JSON, "Authorization": "Bearer tøken".encode("latin-1")},  # type: ignore[dict-item]
            {**JSON, "Authorization": TOKEN},
            {**JSON, "Authorization": "Basic " + TOKEN},
            {**JSON, "Authorization": "Bearer "},
        ):
            assert _send(client, method, path, body, headers=headers).status_code == 401


def test_token_right_writes_succeed(project_dir: Path, fake_ai: Any) -> None:
    client = _client(project_dir, "token", fake_ai)
    pid = _proposal(project_dir)
    for method, path, body in _writes(pid):
        r = _send(client, method, path, body, headers=_bearer())
        assert r.status_code == 200, (method, path, r.text)
    assert any(
        "Changed by a test." in text.decode() for text in _yaml_snapshot(project_dir).values()
    )
    assert ProposalStore(project_dir).list()[0].status == "accepted"
    assert len(fake_ai.calls) == 1


def test_token_reads_stay_open(project_dir: Path) -> None:
    client = _client(project_dir, "token")
    for path in ("/api/health", "/api/project", "/api/graph", "/api/proposals", "/api/auth"):
        assert client.get(path).status_code == 200, path


def test_content_type_is_415(project_dir: Path) -> None:
    for mode in ("token", "open"):
        client = _client(project_dir, mode)
        for method, path, body in _writes(_proposal(project_dir)):
            for ctype in ("text/plain", "application/x-www-form-urlencoded", None):
                headers = {"Authorization": f"Bearer {TOKEN}"}
                if ctype:
                    headers["Content-Type"] = ctype
                r = client.request(method, path, content=b"x=1" if body else b"", headers=headers)
                assert r.status_code == 415, (mode, method, path, ctype)
    # A charset parameter is fine.
    client = _client(project_dir, "open")
    r = client.post(
        f"/api/proposals/{_proposal(project_dir)}/comments",
        content=b'{"text": "x"}',
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    assert r.status_code == 200


def test_auth_check_comes_before_content_type(project_dir: Path) -> None:
    client = _client(project_dir, "token")
    r = client.put("/api/models/customers/docs", content=b"x", headers={"Content-Type": "text/x"})
    assert r.status_code == 401


# --- open --------------------------------------------------------------------------


def test_open_allows_writes_without_token(project_dir: Path, fake_ai: Any) -> None:
    client = _client(project_dir, "open", fake_ai)
    pid = _proposal(project_dir)
    for method, path, body in _writes(pid):
        assert _send(client, method, path, body).status_code == 200, (method, path)


@pytest.mark.parametrize(
    "host",
    ["evil.example.com", "evil.example.com:8484", "127.0.0.1.evil.com", "10.0.0.5:8484", ""],
)
def test_open_rejects_foreign_host_on_all_api_routes(project_dir: Path, host: str) -> None:
    client = _client(project_dir, "open")
    for method, path in (("GET", "/api/project"), ("GET", "/api/auth"), ("POST", "/api/x")):
        r = client.request(method, path, headers={"Host": host, **JSON})
        assert r.status_code == 403, (host, method, path)
        assert "Host" in r.json()["detail"]


@pytest.mark.parametrize(
    "host", ["127.0.0.1:8484", "localhost:8484", "[::1]:8484", "LOCALHOST:8484"]
)
def test_open_accepts_loopback_hosts(project_dir: Path, host: str) -> None:
    client = _client(project_dir, "open")
    assert client.get("/api/project", headers={"Host": host}).status_code == 200


def test_open_checks_the_port(project_dir: Path) -> None:
    client = _client(project_dir, "open")
    assert client.get("/api/project", headers={"Host": "localhost:9999"}).status_code == 403
    assert client.get("/api/project", headers={"Host": "localhost"}).status_code == 403
    # Without a configured port any loopback port is fine.
    anyport = _client(project_dir, "open", port=None)
    assert anyport.get("/api/project", headers={"Host": "localhost:9999"}).status_code == 200


def test_open_allowed_hosts_is_explicit(project_dir: Path) -> None:
    api = create_app(project_dir, serve_ui=False, allowed_hosts=["testserver"])
    assert TestClient(api).get("/api/project").status_code == 200
    assert TestClient(api, base_url="http://other").get("/api/project").status_code == 403
    # Default TestClient host is not loopback, so the check stays strict without the option.
    strict = create_app(project_dir, serve_ui=False)
    assert TestClient(strict).get("/api/project").status_code == 403


def test_host_check_is_only_for_api_routes_in_open_mode(project_dir: Path) -> None:
    other = {"Host": "evil.example.com"}
    assert _client(project_dir, "token").get("/api/project", headers=other).status_code == 200
    assert _client(project_dir, "open").get("/nothing-here", headers=other).status_code != 403


def test_open_refuses_a_public_bind(project_dir: Path) -> None:
    for host in ("0.0.0.0", "192.168.1.5", "example.com"):
        with pytest.raises(ValueError, match="loopback"):
            create_app(project_dir, writes="open", host=host)
    create_app(project_dir, writes="open", host="::1")
    create_app(project_dir, writes="token", write_token="t", host="0.0.0.0")
    create_app(project_dir, writes="off", host="0.0.0.0")


def test_token_mode_needs_a_token(project_dir: Path) -> None:
    for token in (None, ""):
        with pytest.raises(ValueError, match="token"):
            create_app(project_dir, writes="token", write_token=token)
    with pytest.raises(ValueError, match="token"):
        WriteGuard("token", None)


def test_referrer_policy_header(project_dir: Path) -> None:
    r = _client(project_dir, "token").get("/api/project")
    assert r.headers["referrer-policy"] == "no-referrer"


# --- /api/auth ---------------------------------------------------------------------


def test_auth_endpoint(project_dir: Path) -> None:
    open_body = _client(project_dir, "open").get("/api/auth").json()
    assert open_body == {"writes": "open", "token_valid": None}
    off_body = _client(project_dir, "off").get("/api/auth").json()
    assert off_body == {"writes": "off", "token_valid": None}
    client = _client(project_dir, "token")
    assert client.get("/api/auth").json() == {"writes": "token", "token_valid": False}
    bad = client.get("/api/auth", headers={"Authorization": "Bearer nope"})
    assert bad.json() == {"writes": "token", "token_valid": False}
    good = client.get("/api/auth", headers={"Authorization": f"Bearer {TOKEN}"})
    assert good.json() == {"writes": "token", "token_valid": True}
    assert TOKEN not in good.text


# --- mode selection ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("[::1]", True),
        ("localhost", True),
        ("LocalHost", True),
        ("127.0.0.2", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.168.0.2", False),
        ("example.com", False),
        ("", False),
        ("127.0.0.1.evil.com", False),
    ],
)
def test_is_loopback_host(host: str, loopback: bool) -> None:
    assert is_loopback_host(host) is loopback


def test_resolve_write_mode_rules() -> None:
    assert resolve_write_mode("127.0.0.1", None, False).mode == "open"
    assert resolve_write_mode("localhost", "", False).mode == "open"
    assert resolve_write_mode("127.0.0.1", "t", False) == resolve_write_mode("0.0.0.0", "t", False)
    assert resolve_write_mode("127.0.0.1", "t", False).mode == "token"
    assert resolve_write_mode("127.0.0.1", "t", False).generated is False
    assert resolve_write_mode("0.0.0.0", "t", True).mode == "off"
    assert resolve_write_mode("127.0.0.1", None, True).mode == "off"
    assert resolve_write_mode("127.0.0.1", "t", True).token is None


def test_public_bind_without_token_generates_one() -> None:
    a = resolve_write_mode("0.0.0.0", None, False)
    b = resolve_write_mode("0.0.0.0", None, False)
    assert a.mode == "token"
    assert a.generated
    assert a.token
    assert len(a.token) >= 32
    assert a.token != b.token
    assert resolve_write_mode("192.168.1.9", "", False).generated


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("OPENPIPELINE_HOST", "OPENPIPELINE_PORT", "OPENPIPELINE_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("OPENPIPELINE_READ_ONLY", raising=False)
    assert settings_from_env()[2].mode == "open"
    monkeypatch.setenv("OPENPIPELINE_HOST", "0.0.0.0")
    assert settings_from_env()[2].generated
    monkeypatch.setenv("OPENPIPELINE_TOKEN", "abc")
    assert settings_from_env()[2].token == "abc"
    monkeypatch.setenv("OPENPIPELINE_READ_ONLY", "1")
    assert settings_from_env()[2].mode == "off"


def test_browser_url_and_host_header_parsing() -> None:
    assert browser_url("0.0.0.0", 8484, "abc") == "http://localhost:8484/?token=abc"
    assert browser_url("10.0.0.2", 1, "t") == "http://10.0.0.2:1/?token=t"
    assert browser_url("::1", 8484) == "http://[::1]:8484/"
    assert split_host_header("[::1]:8484") == ("::1", 8484)
    assert split_host_header("Localhost") == ("localhost", None)
    assert split_host_header("a:b") == ("a", None)


# --- the serve command -------------------------------------------------------------


class _Run:
    def __init__(self) -> None:
        self.app: Any = None
        self.kwargs: dict[str, Any] = {}

    def __call__(self, app: Any, **kwargs: Any) -> None:
        self.app, self.kwargs = app, kwargs


@pytest.fixture
def uvicorn_run(monkeypatch: pytest.MonkeyPatch) -> _Run:
    for key in ("OPENPIPELINE_TOKEN", "OPENPIPELINE_READ_ONLY", "OPENPIPELINE_HOST"):
        monkeypatch.delenv(key, raising=False)
    run = _Run()
    monkeypatch.setattr("uvicorn.run", run)
    return run


def _auth_of(run: _Run) -> dict[str, Any]:
    client = TestClient(run.app, base_url=f"http://127.0.0.1:{run.kwargs['port']}")
    body: dict[str, Any] = client.get("/api/auth").json()
    return body


def test_serve_on_loopback_stays_open(project_dir: Path, uvicorn_run: _Run) -> None:
    result = runner.invoke(cli_app, ["serve", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert _auth_of(uvicorn_run)["writes"] == "open"
    assert "token" not in result.stdout.lower()


def test_serve_public_bind_prints_token_url(project_dir: Path, uvicorn_run: _Run) -> None:
    result = runner.invoke(cli_app, ["serve", str(project_dir), "--host", "0.0.0.0"])
    assert result.exit_code == 0, result.output
    match = re.search(r"http://localhost:8484/\?token=([\w-]+)", result.stdout)
    assert match, result.stdout
    token = match.group(1)
    assert len(token) >= 32
    assert result.stdout.count(token) == 2  # once bare, once in the link
    client = TestClient(uvicorn_run.app, base_url=LOCAL)
    assert client.get("/api/auth").json() == {"writes": "token", "token_valid": False}
    body = {"description": "x"}
    assert client.put("/api/models/customers/docs", json=body).status_code == 401
    ok = client.put("/api/models/customers/docs", json=body, headers=_bearer(token))
    assert ok.status_code == 200


def test_serve_given_token_is_used_and_not_printed(project_dir: Path, uvicorn_run: _Run) -> None:
    args = ["serve", str(project_dir), "--host", "0.0.0.0", "--token", "mine-123"]
    result = runner.invoke(cli_app, args)
    assert "mine-123" not in result.stdout
    client = TestClient(uvicorn_run.app, base_url=LOCAL)
    ok = client.post("/api/proposals/abc", json={"status": "rejected"}, headers=_bearer("mine-123"))
    assert ok.status_code == 404  # authorised, then the proposal is not there
    assert client.post("/api/proposals/abc", json={}, headers=JSON).status_code == 401


def test_serve_token_from_env_on_loopback(
    project_dir: Path, uvicorn_run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENPIPELINE_TOKEN", "from-env")
    runner.invoke(cli_app, ["serve", str(project_dir)])
    assert _auth_of(uvicorn_run)["writes"] == "token"


def test_serve_empty_token_env_is_ignored(
    project_dir: Path, uvicorn_run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENPIPELINE_TOKEN", "")
    runner.invoke(cli_app, ["serve", str(project_dir)])
    assert _auth_of(uvicorn_run)["writes"] == "open"


@pytest.mark.parametrize("extra", [[], ["--host", "0.0.0.0"], ["--token", "t"]])
def test_serve_read_only_wins(project_dir: Path, uvicorn_run: _Run, extra: list[str]) -> None:
    result = runner.invoke(cli_app, ["serve", str(project_dir), "--read-only", *extra])
    assert "Read-only" in result.stdout
    assert _auth_of(uvicorn_run)["writes"] == "off"


def test_serve_read_only_env_alias(
    project_dir: Path, uvicorn_run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENPIPELINE_READ_ONLY", "1")
    runner.invoke(cli_app, ["serve", str(project_dir), "--host", "0.0.0.0"])
    assert _auth_of(uvicorn_run)["writes"] == "off"


def test_serve_reload_passes_settings_by_env(
    project_dir: Path, uvicorn_run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("OPENPIPELINE_PROJECT_DIR", "OPENPIPELINE_HOST", "OPENPIPELINE_PORT"):
        monkeypatch.setenv(key, "")  # so monkeypatch restores whatever serve sets
    result = runner.invoke(cli_app, ["serve", str(project_dir), "--host", "0.0.0.0", "--reload"])
    assert result.exit_code == 0, result.output
    assert uvicorn_run.app == "openpipeline.app:app"
    assert os.environ["OPENPIPELINE_HOST"] == "0.0.0.0"
    assert len(os.environ["OPENPIPELINE_TOKEN"]) >= 32
    monkeypatch.delenv("OPENPIPELINE_TOKEN")


def test_demo_modes(tmp_path: Path, uvicorn_run: _Run) -> None:
    result = runner.invoke(cli_app, ["demo", "--dir", str(tmp_path / "d1")])
    assert result.exit_code == 0, result.output
    assert _auth_of(uvicorn_run)["writes"] == "open"
    result = runner.invoke(cli_app, ["demo", "--dir", str(tmp_path / "d2"), "--host", "0.0.0.0"])
    assert "?token=" in result.stdout
    assert _auth_of(uvicorn_run)["writes"] == "token"
    result = runner.invoke(cli_app, ["demo", "--dir", str(tmp_path / "d3"), "--read-only"])
    assert _auth_of(uvicorn_run)["writes"] == "off"


# --- MCP over HTTP -----------------------------------------------------------------


def _inner() -> Starlette:
    def hello(_: Request) -> PlainTextResponse:
        return PlainTextResponse("hi")

    return Starlette(routes=[Route("/mcp", hello, methods=["GET", "POST"])])


def test_bearer_middleware() -> None:
    client = TestClient(BearerTokenMiddleware(_inner(), "tok"))
    assert client.get("/mcp").status_code == 401
    assert client.get("/mcp", headers={"Authorization": "Bearer no"}).status_code == 401
    assert client.get("/mcp", headers={"Authorization": "Bearer tok"}).text == "hi"


def test_mcp_http_public_bind_requires_token(project_dir: Path, uvicorn_run: _Run) -> None:
    args = ["mcp", str(project_dir), "--transport", "streamable-http", "--host", "0.0.0.0"]
    result = runner.invoke(cli_app, args)
    assert result.exit_code == 0, result.output
    token = re.search(r"^\s+([\w-]{30,})$", result.stdout, re.M)
    assert token
    with TestClient(uvicorn_run.app, base_url="http://localhost:8485") as client:
        assert client.post("/mcp", json={}).status_code == 401
        ok = client.post("/mcp", json={}, headers={"Authorization": f"Bearer {token.group(1)}"})
        assert ok.status_code != 401


def test_mcp_http_loopback_is_open_unless_token_given(project_dir: Path, uvicorn_run: _Run) -> None:
    base = ["mcp", str(project_dir), "--transport", "streamable-http"]
    runner.invoke(cli_app, base)
    assert not isinstance(uvicorn_run.app, BearerTokenMiddleware)
    runner.invoke(cli_app, [*base, "--token", "t"])
    assert isinstance(uvicorn_run.app, BearerTokenMiddleware)
