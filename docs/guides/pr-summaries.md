# PR summaries

A GitHub Action comments on each pull request that changes your dbt project. The
comment says, in business terms:

- which models were added, changed, or removed, and what each now does
  differently,
- which other models are affected downstream,
- which [business rules](business-rules.md) the change touches, and
- which owners to loop in.

The comment is updated in place on every push, so a pull request only ever has
one.

## Add it to your repository

Create `.github/workflows/openpipeline.yml` in your dbt repository:

```yaml
name: OpenPipeline
on:
  pull_request:
    paths: ["models/**", "dbt_project.yml", "openpipeline.yml"]

permissions:
  contents: read
  pull-requests: write

jobs:
  summary:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: PawanPatil19/openpipeline/actions/pr-summary@v1.0.0
        with:
          project-dir: .   # where dbt_project.yml lives
```

That is all. By default there is no AI, nothing leaves the runner, and no secret
is needed.

The action installs OpenPipeline from its own tag, so the tag you pick decides
which version runs. Pin a full version such as `@v1.0.0`.

The summary is also written to the job's summary page, so it is useful even if you
turn comments off with `comment: "false"`.

## With an AI overview

To add a short plain-words paragraph at the top of the comment, turn on `ai` and
pass an Anthropic API key stored as a repository secret:

```yaml
      - uses: PawanPatil19/openpipeline/actions/pr-summary@v1.0.0
        with:
          ai: "true"
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

It is off by default. When it is on, the SQL and documentation of the changed
models are sent to Anthropic. If the AI call fails, the comment is still posted
without the paragraph. See [AI explanations](ai-explanations.md) for the privacy
details.

## Inputs

| Input | Default | What it does |
| --- | --- | --- |
| `project-dir` | `.` | Path to the dbt project inside the repository. |
| `base-ref` | the PR's base branch | Branch or commit to compare against. |
| `comment` | `"true"` | Post or update a comment. Needs `pull-requests: write`. |
| `github-token` | the workflow token | Token used to post the comment. |
| `ai` | `"false"` | Add the AI overview. Needs `anthropic-api-key`. |
| `anthropic-api-key` | none | Your key. Store it as a secret. |

The action also has one output, `summary-file`, the path to the Markdown file.

## Without GitHub

The action is a thin wrapper around one command, so you can run it anywhere:

```bash
openpipeline review path/to/base path/to/head          # print Markdown
openpipeline review base head -o summary.md            # write a file
openpipeline review base head --ai                     # with the AI overview
```

`base` and `head` are two folders that each hold a version of the project. Check
out the base branch into a second folder (for example with `git worktree add`) and
point at both. See the [command line reference](../reference/cli.md#openpipeline-review).

## Fork pull requests

GitHub gives workflows that run on fork pull requests a read-only token and no
secrets. Posting the comment will fail there, and so will the AI overview. If you
accept fork pull requests, set `comment: "false"` for them and read the summary
on the job summary page instead.
