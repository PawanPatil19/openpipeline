# Security policy

## Reporting a vulnerability

Please do **not** open a public issue. Use GitHub's
[private vulnerability reporting](https://github.com/PawanPatil19/openpipeline/security/advisories/new)
instead. We aim to reply within 3 working days.

## How OpenPipeline is meant to be run

OpenPipeline is a local-first developer tool. Keep these in mind:

- The web API and the HTTP MCP server have **no authentication yet**. Anyone
  who can reach them can read your dbt project and accept proposals, which
  writes files. By default they listen on `127.0.0.1` only. The Docker image
  listens on all interfaces inside the container, so only publish its ports to
  your own machine or a private network.
- AI agents can only create proposals. Proposals are written to
  `.openpipeline/proposals/` and are applied only when a person accepts them.
  Paths that leave the project folder, or touch `.git` or `.openpipeline`, are
  refused.
- OpenPipeline never runs your SQL and never connects to your warehouse.
