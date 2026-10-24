# Editing descriptions

Good descriptions are the cheapest documentation a dbt project can have, and they
make every story better. You can write them in the UI, and they are saved into
your own YAML files.

## In the UI

1. Select a model.
2. Click **Edit description** to change the model's description, or **Edit column
   descriptions** to change the notes on its columns.
3. Type, then click **Save**.

OpenPipeline writes the text into the model's YAML file, for example
`schema.yml`. It keeps the comments and layout of the rest of the file. If the
model has no entry in any YAML file yet, it adds one in a new file next to the
SQL file.

The change is an ordinary file change. Look at it with your version control
tool, commit it, or revert it like any other.

## What gets written, and who writes it

A person clicking **Save** writes the file straight away. That is the one place
OpenPipeline writes without a proposal, because you are right there deciding.

AI agents never write directly. When an agent wants to improve a description, it
calls the `propose_docs` tool, which files a normal proposal containing the
updated YAML. You review it and accept or reject it, like any other change. See
[Working with AI agents](ai-agents.md).

## Safety checks

OpenPipeline refuses to write outside your project folder, inside `.git`, or
inside `.openpipeline`. If you also edit the file by hand while the editor is
open, the newest save wins, so keep an eye on your own editor if you work in both.

## Tips

- Write for a new teammate. Say what one row is, and what the numbers mean.
- Use [AI explanations](ai-explanations.md) to get a first draft. The
  **Use as description** and **Use column notes** buttons fill in the editors, and
  nothing is saved until you click **Save**.
- Put the owner on the model with `meta: {owner: growth-team}` so people know
  who to ask.
