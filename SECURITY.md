# Security policy

## Reporting a vulnerability

Please do **not** open a public issue. Use GitHub's
[private vulnerability reporting](https://github.com/PawanPatil19/openpipeline/security/advisories/new)
instead. We aim to reply within 3 working days.

## How OpenPipeline is meant to be run

OpenPipeline is a local-first developer tool. Keep these in mind:

- **Writes are protected, reads are not.** Anyone who can reach the server can
  read your dbt project. Changing things (saving descriptions, accepting
  proposals, comments, and AI calls, which cost money) depends on the write mode:
  - On `127.0.0.1`, `::1`, or `localhost` with no token, writes are open, and
    `/api` requests must carry a loopback `Host` header (a defence against DNS
    rebinding).
  - With `--token` (or `OPENPIPELINE_TOKEN`), or on any other address, writes need
    `Authorization: Bearer <token>`. If you listen on a non-loopback address
    without a token, one is generated and printed at startup. OpenPipeline never
    runs open on a public bind. The Docker image therefore always uses a token.
  - With `--read-only` (or `OPENPIPELINE_READ_ONLY=1`), every write is refused.
  - Writes must be sent as `application/json`, so a web page on another site cannot
    post a form to your server.

  There is one shared token, not user accounts, and no TLS. Put the server behind
  HTTPS if it crosses a network you do not trust. See
  [Write access and security](docs/reference/security.md).
- The MCP server over stdio is a local process with no port. Over streamable HTTP
  it follows the same rule: open on loopback, a Bearer token on any other
  address.
- AI agents can only create proposals. Proposals are written to
  `.openpipeline/proposals/` and are applied only when a person accepts them.
  Paths that leave the project folder, or touch `.git` or `.openpipeline`, are
  refused.
- OpenPipeline never runs your SQL and never connects to your warehouse.
