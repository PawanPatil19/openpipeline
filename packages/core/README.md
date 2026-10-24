# openpipeline-core

The engine behind OpenPipeline. It has no web or server dependencies, so you
can use it from scripts, CI jobs, or other tools.

```python
from openpipeline_core import load_project, explain_model

project = load_project("examples/jaffle_shop")
print(explain_model(project, "customers").summary)
```

It reads a dbt project in one of two ways:

1. **From `target/manifest.json`** when it exists (run `dbt parse` first). This
   is the most accurate, because dbt has already resolved every `ref()`,
   `source()`, macro, and config.
2. **From the files directly** when there is no manifest. This needs no dbt
   install, no profile, and no warehouse credentials, so anyone can open a repo
   and look around.
