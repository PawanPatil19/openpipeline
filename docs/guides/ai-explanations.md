# AI explanations

OpenPipeline works fully without AI. If you want an explanation that reads as if
a person wrote it, you can turn one on with your own Anthropic API key. It is
always optional and always off until you ask.

## Turn it on

```bash
pip install 'openpipeline[ai]'
export ANTHROPIC_API_KEY=sk-ant-...
openpipeline serve path/to/project
```

The Docker image already includes the extra. Pass the key with
`-e ANTHROPIC_API_KEY`.

Then select a model and click **Explain with AI**. The answer has:

- a short summary in plain words,
- things worth double-checking,
- a suggested model description, and
- suggested notes for each column.

The buttons **Use as description** and **Use column notes** only fill in the
editors. Nothing is saved until you click **Save**. See
[Editing descriptions](editing-descriptions.md).

From the terminal:

```bash
openpipeline explain customers --ai
```

If you do not have a key, the panel tells you what is missing instead of
failing.

## Bring your own key

OpenPipeline never ships a key and has no account system. Calls go from your
machine straight to Anthropic with your key, and you pay Anthropic for them. The
key is read from the usual places: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
or a profile set up with the Anthropic command line tool.

## Privacy

!!! warning "What is sent"
    When you click **Explain with AI** or pass `--ai`, OpenPipeline sends the SQL
    and documentation of the model you asked about, and of the models it reads
    from, to Anthropic. Nothing is sent at any other time.

- Without a key, or with `OPENPIPELINE_AI=off`, nothing can be sent.
- Your warehouse is never contacted, and no data rows are sent. Only code and
  descriptions are.
- If your SQL or descriptions are confidential, check your company's rules before
  turning this on.

## Caching

Answers are saved in `.openpipeline/cache/ai` inside your project. The cache key
is a hash of everything that was sent, so asking again about an unchanged model
is instant and free, and changing the SQL or its parents asks again.

Add `.openpipeline/` to your `.gitignore`. It also holds
[proposals](ai-agents.md).

## Choosing the model

The default model is `claude-opus-5-5`. To use a different one, set
`OPENPIPELINE_AI_MODEL`:

```bash
export OPENPIPELINE_AI_MODEL=claude-sonnet-5-5
```

To switch AI off completely, even if a key is present:

```bash
export OPENPIPELINE_AI=off
```

## In PR summaries

`openpipeline review BASE HEAD --ai` adds an "In plain words" paragraph to the top
of a [PR summary](pr-summaries.md). If the AI call fails, the normal summary is
still printed.
