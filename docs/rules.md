# Business rules

Every team has rules that live only inside SQL: "an order counts as revenue only
once it is shipped", "lifetime value leaves out refunds". OpenPipeline lets you
name those rules in one place, say who owns each one, link them to the models
and columns that carry them, and flag them whenever a change touches them.

## The rules file

Rules live in `openpipeline.yml` at the root of your dbt project, next to
`dbt_project.yml`. The file is part of your project, so it is versioned and
reviewed like any other file.

```yaml
rules:
  - id: shipped-revenue
    name: Revenue counts once an order is shipped
    description: >
      An order only counts as revenue after it has shipped. Orders that are
      placed but not shipped are not revenue yet.
    owner: finance-team
    tags: [finance, orders]
    applies_to:
      - model: orders
      - model: daily_revenue
        columns: [revenue]
```

Each rule has these fields.

| Field | Required | What it means |
| --- | --- | --- |
| `id` | yes | A short unique name using lowercase letters, numbers, dashes, and underscores. Other files point to the rule by this id. |
| `name` | no | The title people see. Defaults to the id. |
| `description` | no | The rule in plain English. |
| `owner` | no | The person or team to ask about the rule. They are added to "Owners to loop in" when a change touches it. |
| `tags` | no | Free labels, such as `finance`. |
| `applies_to` | no | The models that carry the rule. Each entry has a `model` and, optionally, a list of `columns` when the rule is about specific columns. |

## Linking from dbt's own YAML

You can also link a rule from the model or column that implements it. Use
`meta.rules` with a list of rule ids:

```yaml
models:
  - name: orders
    meta:
      rules: [shipped-revenue]
    columns:
      - name: amount
        meta:
          rules: [lifetime-value]
```

This works when OpenPipeline reads your files and when it reads
`target/manifest.json`. Links from both places are merged. A rule that is linked
twice to the same model is only listed once, and its columns are combined.

## What you see

- The **Rules** tab lists every rule with its owner, description, and linked
  models. Click a model to open it on the graph.
- The model panel has a **Business rules** section, and graph boxes for models
  that carry a rule show a small badge.
- `openpipeline rules` prints the rules grouped by owner.
- AI agents see the rules through the `list_rules` tool and in the output of
  `get_model` and `explain`. They are told to name any rule a change touches in
  the rationale of their proposal.

## Pull request summaries

`openpipeline review BASE HEAD` includes the rules in its summary.

- **Business rules touched** lists each rule that a changed model carries, with
  its owner, where it applies, and why it is listed: the model was modified, a
  column the rule names was removed, the model is new, or the model was deleted.
  Changes that only reword a model's description are not counted, because they
  do not change what the model computes.
- **Business rules that may be affected** lists rules carried by models
  further downstream. They read from something that changed, so their results
  may differ.
- **Changes to `openpipeline.yml`** lists rules that were added, removed,
  renamed, reworded, given a new owner, or linked to different models.
- Each changed model also lists its rules under its own heading.
- The owners of touched rules, and of rules that were added, removed, or
  changed in the file, are added to "Owners to loop in".

## Problems are warnings, not errors

If something in the rules is wrong, OpenPipeline still loads your project and
shows a warning in the UI banner and in `GET /api/project`. It warns about:

- a rule that points to a model that does not exist (the link is ignored),
- a `meta.rules` entry that names a rule id that is not defined,
- two rules with the same id (the first one is kept),
- a rule with no id, or an entry that is not a mapping,
- a file that cannot be parsed.

OpenPipeline does not check that the columns you list exist, because it only
knows the columns that are documented or that it can read from the SQL.
