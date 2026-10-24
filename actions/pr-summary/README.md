# OpenPipeline PR summary action

Posts a comment on each pull request that explains, in plain words, which dbt
models changed, what they now do differently, which downstream models are
affected, and which owners to loop in.

```yaml
# .github/workflows/openpipeline.yml in your dbt repository
name: OpenPipeline
on:
  pull_request:
    paths: ["models/**", "dbt_project.yml"]

permissions:
  contents: read
  pull-requests: write

jobs:
  summary:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: PawanPatil19/openpipeline/actions/pr-summary@v0
        with:
          project-dir: .   # where dbt_project.yml lives
```

## Optional: AI overview

Add a short plain-words paragraph at the top of the comment, written by Claude.

```yaml
      - uses: PawanPatil19/openpipeline/actions/pr-summary@v0
        with:
          ai: "true"
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

This is off by default. When it is on, the SQL and documentation of the changed
models are sent to Anthropic. If the AI call fails, the comment is still posted
without the paragraph.

| Input | Default | What it does |
| --- | --- | --- |
| `ai` | `"false"` | Install `openpipeline[ai]` and add the overview. |
| `anthropic-api-key` | none | Your key. Store it as a repository secret. |

The comment is updated in place on every push, so the pull request only ever
has one.
