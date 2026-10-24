"""One-command demo: a copy of the example project with a proposal waiting for review.

``openpipeline demo`` copies the bundled jaffle_shop project to a folder you can
edit, files one realistic proposal from an imaginary agent so the review flow is
visible straight away, and then starts the server. Nothing here writes dbt files
without a person: the proposal is only filed, and accepting it is up to you.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from openpipeline.proposals import FileChange, Proposal, ProposalStore

_IGNORE = shutil.ignore_patterns(".openpipeline", "target", "__pycache__", "logs", ".DS_Store")

NEW_MODEL_PATH = "models/marts/revenue_by_month.sql"
NEW_MODEL_SQL = """select
    date_trunc('month', order_date) as month,
    count(order_id) as number_of_orders,
    sum(amount) as revenue
from {{ ref('orders') }}
where status = 'shipped'
group by 1
"""

SCHEMA_PATH = "models/marts/schema.yml"
SCHEMA_ADDITION = """  - name: revenue_by_month
    description: Revenue for each calendar month. Only shipped orders count.
    meta:
      owner: finance-team
      rules: [monthly-revenue]
    columns:
      - name: revenue
        description: Total paid for shipped orders in the month, in dollars.
"""

RULES_PATH = "openpipeline.yml"
RULES_ADDITION = """
  - id: monthly-revenue
    name: Revenue is reported by calendar month
    description: >
      Finance reports revenue per calendar month, counting only orders that have
      shipped. Orders that are placed but not shipped are not revenue yet.
    owner: finance-team
    tags: [finance, orders]
    applies_to:
      - model: revenue_by_month
        columns: [revenue]
"""
DOLLARS_RULE_COMMENT = "    # The stg_payments model links to this rule from its dbt YAML.\n"
DOLLARS_RULE_LINKS = DOLLARS_RULE_COMMENT + (
    "    applies_to:\n      - model: revenue_by_month\n        columns: [revenue]\n"
)

RATIONALE = (
    "Finance asked for monthly revenue and there is no model for it yet. This adds "
    "`revenue_by_month`, built on `orders`, which only counts shipped orders. It also "
    "touches business rules: a new rule, `monthly-revenue`, records how the number is "
    "defined, and the existing `amounts-in-dollars` rule now lists the new model, because "
    "the revenue column relies on amounts already being in dollars. Nothing downstream "
    "reads this model yet, so no existing report changes."
)


def example_dir() -> Path:
    """Where the bundled example lives: inside the wheel, or in the repo when run from source."""
    packaged = Path(__file__).parent / "_example"
    if packaged.is_dir():
        return packaged
    repo = Path(__file__).resolve().parents[4] / "examples" / "jaffle_shop"
    if repo.is_dir():
        return repo
    raise FileNotFoundError("The bundled example project was not found.")


def prepare_demo(target: Path | None = None) -> tuple[Path, Proposal]:
    """Copy the example project and file one pending proposal. Returns both."""
    if target is None:
        dest = Path(tempfile.mkdtemp(prefix="openpipeline-demo-")) / "jaffle_shop"
    else:
        dest = target.resolve()
        if dest.exists() and any(dest.iterdir()):
            raise FileExistsError(f"{dest} already exists and is not empty.")
    shutil.copytree(example_dir(), dest, ignore=_IGNORE, dirs_exist_ok=True)
    return dest, _seed_proposal(dest)


def _seed_proposal(root: Path) -> Proposal:
    schema = (root / SCHEMA_PATH).read_text(encoding="utf-8").rstrip("\n") + "\n"
    rules = (root / RULES_PATH).read_text(encoding="utf-8")
    if DOLLARS_RULE_COMMENT in rules:
        rules = rules.replace(DOLLARS_RULE_COMMENT, DOLLARS_RULE_LINKS)
    rules = rules.rstrip("\n") + "\n" + RULES_ADDITION
    proposal = Proposal(
        title="Add monthly revenue for finance",
        rationale=RATIONALE,
        author="claude-agent",
        changes=[
            FileChange(path=NEW_MODEL_PATH, content=NEW_MODEL_SQL),
            FileChange(path=SCHEMA_PATH, content=schema + SCHEMA_ADDITION),
            FileChange(path=RULES_PATH, content=rules),
        ],
    )
    return ProposalStore(root).create(proposal)
