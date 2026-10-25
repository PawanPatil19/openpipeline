# Real-project fixtures

Public dbt projects used by the core and server tests, so the story engine can be
measured on real code instead of the 5-model toy in `examples/jaffle_shop`.
Tests reach them through the `dbt_labs_jaffle_dir` and `tuva_dir` fixtures in each
`conftest.py`.

| Fixture | Source | Commit | Models | License |
| --- | --- | --- | --- | --- |
| `jaffle_shop_dbt_labs/` | https://github.com/dbt-labs/jaffle-shop | `5beb145b00f5465ec759cfcdd9745e858818cf95` | 13 | see below |
| `tuva/` | https://github.com/tuva-health/tuva (`integration_tests`) | `9ab0d1c3e4a920f5acebdd5f9a2f456fb20fe7e2` | 309 | Apache-2.0 |

## jaffle_shop_dbt_labs

dbt Labs' public demo project, used unmodified and only for testing (it is not
shipped in any package): https://github.com/dbt-labs/jaffle-shop. The upstream
repository declares no license. All rights stay with dbt Labs; we will remove it on
request. Contents: `dbt_project.yml`, `packages.yml`, `models/`, `macros/` and the slimmed
`target/manifest.json`. Seeds and `dbt_packages` are not copied.

## tuva

Apache-2.0 (`LICENSE`, `NOTICE`). Manifest-only: `dbt_project.yml` plus the slimmed
`manifest.json.gz`. No SQL files are vendored (too large); the manifest carries
`raw_code` and `compiled_code`. Tests gunzip it into a temp project directory.

## How they were generated

Both were compiled with dbt-core 1.12 and dbt-duckdb. `hub.getdbt.com` was not
reachable, so packages were placed in `dbt_packages/` by hand instead of `dbt deps`:

- jaffle-shop: `dbt_utils` 1.4.1 and `dbt-audit-helper` (main), copied into `dbt_packages/`.
- tuva: `dbt_utils` 1.4.1 in `integration_tests/dbt_packages/`, plus
  `the_tuva_project` as a symlink to the repo root (`../..`). The optional packages in
  `packages.yml` (ahrq_quality_indicators, ccsr, cms_chronic_conditions, cms_hcc,
  fhir_preprocessing, nyu_ed_classification, quality_measures, semantic-layer) were dropped.

```sh
# jaffle-shop (its require-dbt-version is >=2.0.0, hence --no-version-check)
cd jaffle-shop
dbt compile --no-version-check --profiles-dir <dir with a duckdb "default" profile>

# tuva
cd tuva/integration_tests
dbt compile --no-version-check --profiles-dir <same> \
  --vars '{claims_enabled: true, clinical_enabled: true, provider_attribution_enabled: true}'
```

The three vars are also set in the project's own `dbt_project.yml`.

Manifests are then slimmed (compact, key-sorted JSON, so regenerating diffs cleanly):

```sh
python scripts/slim_manifest.py jaffle-shop/target/manifest.json \
  fixtures/jaffle_shop_dbt_labs/target/manifest.json
python scripts/slim_manifest.py tuva/integration_tests/target/manifest.json \
  fixtures/tuva/manifest.json.gz --gzip
```

`.gitignore` ignores `target/` but re-includes `fixtures/**/target/`.
