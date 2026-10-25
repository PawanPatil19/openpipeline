# Write access and security

Anyone who can reach the server can read your dbt project. What they can *change*
depends on the **write mode**, which the server picks when it starts.

Writes are everything that changes files or costs money:

| Request | What it does |
| --- | --- |
| `PUT /api/models/{name}/docs` | Writes descriptions into your dbt YAML. |
| `POST /api/proposals/{id}` | Accepts or rejects a proposal. Accepting writes files. |
| `POST /api/proposals/{id}/comments` | Adds a comment. |
| `POST /api/models/{name}/ai-explanation` | Calls the Anthropic API with your key. |

Every `POST`, `PUT`, `PATCH`, and `DELETE` under `/api` is treated as a write, so a
route added later is covered without anyone remembering to protect it. Reads (`GET`)
are always open.

## The three modes

| Mode | Writes | When you get it |
| --- | --- | --- |
| `open` | Anyone who can reach the server. | Listening on `127.0.0.1`, `::1`, or `localhost` with no token. This is the everyday local experience. |
| `token` | Only requests with `Authorization: Bearer <token>`. | You gave `--token` (or `OPENPIPELINE_TOKEN`), or you listen on any other address. |
| `off` | None. They answer `403`. | You passed `--read-only` (or `OPENPIPELINE_READ_ONLY=1`). |

The rules, in order:

1. `--read-only` means `off`.
2. A token means `token`.
3. No token and a loopback address means `open`.
4. No token and any other address (for example `--host 0.0.0.0`, or the Docker
   image) means `token` with a random token. OpenPipeline never runs open on a public
   bind.

```text
$ openpipeline serve --host 0.0.0.0
Listening on 0.0.0.0, so writes need a token. Generated for this run:
  q3x...
Open this link to use it in the browser:
  http://localhost:8484/?token=q3x...
```

Open the printed link. The web UI keeps the token for that browser tab only
(`sessionStorage`), removes it from the address bar, and sends it with every change.
If you open the server without the link, the first change that is refused shows a
box to paste the token into. In read-only mode the editing, accept, reject, comment,
and AI buttons are hidden.

Choose your own token to keep it stable between runs:

```bash
OPENPIPELINE_TOKEN="$(openssl rand -base64 24)" openpipeline serve --host 0.0.0.0
```

A token you choose is never printed.

## Responses

| Status | Meaning |
| --- | --- |
| `401` | Token mode, and the `Authorization` header is missing or wrong. |
| `403` | Read-only mode, or (in open mode) a `Host` header that is not a loopback name. |
| `415` | The write was not sent with `Content-Type: application/json`. |

Writes must be JSON, even `ai-explanation`, which has no body. This stops a web page
on another site from posting a form to a server on your machine.

## Checking the mode

`GET /api/auth` says how writes are handled, and in token mode whether your token is
right. It never returns the token.

```json
{ "writes": "token", "token_valid": false }
```

`writes` is `open`, `token`, or `off`. `token_valid` is `null` unless the mode is
`token`.

## Open mode and the Host header

A malicious web page can make your browser talk to `127.0.0.1`. To stop DNS
rebinding, in open mode every `/api` request must have a `Host` header that is
`localhost` or a loopback IP, on the port the server listens on. Open the UI as
`http://127.0.0.1:8484` or `http://localhost:8484`. A reverse proxy that forwards a
different `Host` gets `403`; give the server a token instead and it will not be open.

## Docker

The image listens on `0.0.0.0`, so it always uses a token:

```bash
docker run --rm -p 8484:8484 -v "$PWD:/project" ghcr.io/pawanpatil19/openpipeline
docker logs <container>    # shows the token and the link
```

| You want | Run with |
| --- | --- |
| A token you choose | `-e OPENPIPELINE_TOKEN=...` |
| No writes at all | `-e OPENPIPELINE_READ_ONLY=1` |

With Docker Compose, set `OPENPIPELINE_TOKEN` once and both services use it. Publish
ports to your own machine (`-p 127.0.0.1:8484:8484`) unless you mean to share them.

## MCP server

`openpipeline mcp` over **stdio** (the default) is a local process that the agent
starts. It has no network port, so it is local-only and needs no token.

Over **streamable HTTP**, the same rules apply to the endpoint: loopback with no
token is open, and any other address requires `Authorization: Bearer <token>` on
every request (a random one is printed if you did not give `--token`). Agents still
can only *propose* changes. A person accepts them in the web UI, which is the only
path that writes dbt files.

## What this does not do

- It is one shared token, not user accounts. Anyone with the token can accept
  proposals.
- It does not encrypt traffic. Over a network, put it behind HTTPS (a reverse proxy
  or tunnel). A token sent over plain HTTP can be read by anyone on the path.
- Reads are open. Anyone who can reach the port can read your project's SQL and
  descriptions. Keep it on a trusted network.
