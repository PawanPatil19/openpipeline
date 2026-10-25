# HTTP API

`openpipeline serve` exposes the same API that the web UI uses. It is handy for
scripts, dashboards, and your own tools.

The live, always-correct reference is built into the server. Start it and open
**<http://127.0.0.1:8484/api/docs>** to read every route, see the exact request
and response shapes, and try them out. The raw schema is at `/openapi.json`.

This page is a map of what is there.

!!! warning "Writes can need a token"
    Reads are always open. Writes (`PUT`, `POST`) are open only when the server
    listens on a loopback address with no token. Otherwise they need
    `Authorization: Bearer <token>` (`401` without it), or they are refused with
    `403` in read-only mode. Writes must be sent as `Content-Type: application/json`
    (`415` otherwise). `GET /api/auth` reports the mode. See
    [Write access and security](security.md).

## Project and graph

| Method and path | What it returns |
| --- | --- |
| `GET /api/health` | `{"status": "ok", "version": "..."}` |
| `GET /api/auth` | `{"writes": "open" \| "token" \| "off", "token_valid": true \| false \| null}`. `token_valid` is only set in token mode. Never contains the token. |
| `GET /api/project` | Project name, how it was loaded, model and source counts, warnings. |
| `GET /api/graph` | Every node and edge of the graph. |
| `GET /api/models/{name}` | One model: SQL, columns, config, dependencies. |
| `GET /api/models/{name}/story` | The plain-English story. |
| `GET /api/models/{name}/business-story` | The same story in the glossary's [business words](../guides/business-words.md), with the technical story inside it as `technical`. |
| `GET /api/models/{name}/impact` | Upstream and downstream model names. |
| `PUT /api/models/{name}/docs` | Save a new description and column descriptions into the YAML file. Body: `{"description": "...", "columns": {"column_name": "..."}}`. Leave out anything that should stay as it is. Answers `400` if the edit cannot be made. |

`{name}` is a model name. Routes that take a model answer `404` for a name that
does not exist.

## AI explanations

| Method and path | What it does |
| --- | --- |
| `GET /api/ai` | Whether AI is available, and which model it would use. |
| `POST /api/models/{name}/ai-explanation` | Ask for an AI explanation. Add `?refresh=true` to skip the cache. Answers `503` when AI is not available (the message says why) and `502` when the call to Anthropic fails. |

## Sample rows

| Method and path | What it returns |
| --- | --- |
| `GET /api/sample/status` | Whether DuckDB is installed and where sample data comes from. |
| `GET /api/models/{name}/sample?limit=20` | Columns and rows. `limit` is from 1 to 200 and defaults to 20. When a preview cannot run, the answer is still `200` with an `error` field that names the missing table. |

## Search and column lineage

| Method and path | What it returns |
| --- | --- |
| `GET /api/search?q=...&limit=20` | Matching models, sources, seeds, and columns, best first. `limit` is from 1 to 100. |
| `GET /api/models/{name}/columns` | A model's columns with their descriptions and the columns each is built from. |
| `GET /api/models/{name}/columns/{column}/lineage` | Upstream and downstream columns, nearest first, across every hop. |

## Business rules

| Method and path | What it returns |
| --- | --- |
| `GET /api/rules` | Every rule, plus warnings. |
| `GET /api/models/{name}/rules` | The rules a model carries. |

## Glossary

| Method and path | What it returns |
| --- | --- |
| `GET /api/glossary` | Every [glossary](../guides/business-words.md) term, plus warnings. |

## Proposals

| Method and path | What it does |
| --- | --- |
| `GET /api/proposals?status=pending` | List proposals, newest first, optionally by status (`pending`, `accepted`, `rejected`, or `superseded`). |
| `GET /api/proposals/{id}/preview` | What the proposal would do to the project as it is now. Answers `422` when the files cannot be applied. |
| `POST /api/proposals/{id}` | Accept or reject. Body: `{"status": "accepted" \| "rejected", "reason": "...", "force": false}`. |
| `POST /api/proposals/{id}/comments` | Add a comment. Body: `{"text": "...", "author": "reviewer"}`. |

Accepting answers `409` with `{"code": "stale", "changed_files": [...]}` when a file
changed after the proposal was made. Send the request again with `"force": true` to
accept anyway.

!!! note
    The API can accept a proposal, because accepting is a person's decision. Agents
    do not use the HTTP API. They use the [MCP server](../guides/ai-agents.md),
    which can only propose.
