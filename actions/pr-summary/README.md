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

The comment is updated in place on every push, so the pull request only ever
has one.
