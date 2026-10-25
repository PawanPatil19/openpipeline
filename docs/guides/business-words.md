# Business words

Not everyone who reads a story reads SQL. A finance lead does not want to see
"order_cost: the total of supply_cost per order_id". They want "Order cost: the total
of Supply cost per Order". **Business words** mode tells every story in your
business's own words, and tucks the SQL and the technical names behind **Show
details**.

It is deterministic, like the rest of the story engine: it needs no AI model and no
network, and it gives the same answer every time.

## Turn it on

In the web UI, open a model and choose **Business words** above its story. The
choice is remembered in your browser. **Technical** switches back.

In business words you see:

- a title, which is the model's label, and a summary in plain sentences, such as
  "Orders brings together Staged orders and Order items into one row per Order"
- how it is built, as steps in business words (plain imports such as "Reads
  stg_orders." are left out)
- **What you get**: each column as a label and what it means
- **Words used**: the glossary definitions for the terms in the story
- a collapsed **Show details** that opens up the model name, file, SQL-ish steps,
  filters, and technical column names

Hover over, or tab to, a word with a dotted underline to read its definition. Press
Enter or tap to keep it open, and Escape to close it.

On the command line:

```bash
openpipeline explain orders --business
openpipeline explain orders --business --json   # includes the technical story too
```

## Write a glossary

A glossary is a list of terms in `openpipeline.yml`, next to `rules:`. Each term names
a column, model, source, or seed and says what the business calls it.

```yaml
glossary:
  - name: customer_id          # a column, model, source or seed name
    label: Customer
    definition: The person who placed the order.   # optional
    aliases: [user_id]         # optional: other names that mean the same thing
  - name: orders
    label: Orders
    definition: One row per order placed in a shop.
```

| Field | Required | What it means |
| --- | --- | --- |
| `name` | yes | The model, column, source, or seed name. A source table can be written as `source.table` or, if no model has the same name, just `table`. Case does not matter. |
| `label` | yes | What your business calls it. |
| `definition` | no | What it means, in a sentence. Shown on hover and in **Words used**. |
| `aliases` | no | More names that use the same label and definition, such as `user_id` for `customer_id`. |

The **Glossary** tab lists every term.

### Labels from dbt's own YAML

A model or a column can carry its label in dbt's `meta`:

```yaml
models:
  - name: customers
    meta:
      label: Customers
      definition: One row per person who has signed up.
    columns:
      - name: lifetime_value
        meta:
          label: Lifetime value
```

`meta` works the same way when OpenPipeline reads files and when it reads
`target/manifest.json`. A column label applies to every column with that name. If
the same name has a label in `openpipeline.yml` and in `meta`, the
`openpipeline.yml` entry wins (a definition it leaves out is filled in from `meta`).
If two models give the same column different labels, the first is kept and a
warning says so.

### Names you do not list

Anything without a term still gets a readable label, worked out from its name:

| Name | Label |
| --- | --- |
| `order_items_subtotal` | Order items subtotal |
| `customer_id` | Customer ID |
| `is_food_order` | Is food order |
| `stg_orders`, `fct_orders`, `dim_customers` | Orders, Orders, Customers |
| `claims__medical_claim` (Tuva style) | Medical claim |

The common dbt prefixes `stg_`, `int_`, `fct_`, `fact_`, `dim_`, `base_`, `src_`, and
`mart_` are dropped from model names (not from column names), and for a name written
`namespace__part` only the part after the last double underscore is used. When two
models would end up with the same label, such as `orders` and `stg_orders`, the
prefixed one is told apart ("Staged orders"), as is a source table ("Raw orders").
A label you write in the glossary is never changed.

A column description from dbt is used as the column's definition when the glossary
has none.

### Warnings

Mistakes never stop OpenPipeline. They show up as warnings in the project banner
and on the Glossary tab:

- a term without a `name` is skipped
- a term without a `label` is kept, with a label worked out from its name
- a name or alias used twice keeps the first term

## What is and is not replaced

Labels are put in by recognising names in the story, not by searching and replacing
text. A word counts as a name when it is `snake_case` or is the name of a model,
source, or column. Quoted values such as `'completed'` are never touched, nor are
function and macro names such as `date_trunc(`. The words the story itself uses
("the total of", "per") are never mistaken for column names, so a column called
`total` still reads correctly.

## Suggestions from AI agents

Agents can call the MCP tool `propose_glossary_term` with a `name`, a `label`, and a
`definition`. It files a [proposal](ai-agents.md) that edits `openpipeline.yml`,
keeping every other line, comment, and rule in the file. Nothing is written until a
person accepts it in the UI. If the name already has a term, the proposal updates
its label and definition and keeps its aliases.

Agents can also read the glossary with `list_glossary`, and `explain` returns a
`business` view next to the technical story.

## From the API

| Method and path | What it returns |
| --- | --- |
| `GET /api/models/{name}/business-story` | The story in business words. The technical story is inside it as `technical`. |
| `GET /api/glossary` | `{"terms": [...], "warnings": [...]}` |

See the [HTTP API](../reference/api.md).
