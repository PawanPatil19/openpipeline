# Releasing

Releases are cut by pushing a version tag. The
[release workflow](https://github.com/PawanPatil19/openpipeline/blob/main/.github/workflows/release.yml) then:

1. Checks the tag matches the version in every package.
2. Builds the web UI into the Python package and builds both wheels.
3. Publishes `openpipeline-core` and `openpipeline` to PyPI.
4. Builds and pushes a multi-arch Docker image (amd64 and arm64) to
   `ghcr.io/pawanpatil19/openpipeline`, with an SBOM and provenance.
5. Creates a GitHub release with generated notes and the wheels attached.

Tags with a pre-release suffix (for example `v0.2.0-rc1`) are marked as
pre-releases and do not move the `latest` Docker tag.

## Steps

```bash
python3 scripts/bump_version.py 0.2.0
uv lock
# Move the Unreleased section of CHANGELOG.md under a 0.2.0 heading.
git commit -am "Release 0.2.0"
git tag v0.2.0
git push origin main v0.2.0
```

`bump_version.py` sets the version in both Python packages, in
`apps/web/package.json`, and in the exact `openpipeline-core==` pin of the app.
Never edit those by hand. Check them with
`python3 scripts/bump_version.py --check 0.2.0`. The release workflow runs the
same check against the tag and stops if anything differs.

## One-time setup

These need a repository admin and only have to be done once, before the first tag.

- **PyPI trusted publishing.** On PyPI, add a "pending publisher" for each
  package, with owner `PawanPatil19`, repository `openpipeline` and workflow
  `release.yml`:
  - `openpipeline-core` with environment `pypi-core`
  - `openpipeline` with environment `pypi`

  PyPI refuses two pending publishers with the same repository, workflow and
  environment, which is why each package has its own environment. The first
  release creates each project. No API token is stored in GitHub.
- **GitHub environments.** Create environments named `pypi-core` and `pypi`
  under Settings > Environments. Adding yourself as a required reviewer gives
  every release a final manual approval.
- **GHCR visibility.** The first image is pushed as a private package. After it
  appears, make `openpipeline` public under the repository's Packages settings so
  `docker pull ghcr.io/pawanpatil19/openpipeline` works without logging in.
- **Branch protection.** Require the `All checks passed` status on `main`. It
  covers the Python matrix, the web checks, the Docker build, and the PR summary
  action. The site build (`Build docs`) runs only when site, docs, or web files change, so add
  it as a required check as well if you want it enforced.

## Cutting 0.1.0 (the first release)

The version is 0.x on purpose: the project is young and names may still change.
1.0 comes after real teams have used it.

1. Start from an up-to-date `main` with every check green.
2. Confirm the one-time setup above is done. A missing PyPI publisher fails the
   release after the tag is pushed.
3. Optional but recommended: rehearse on TestPyPI. Add the same two pending
   publishers on <https://test.pypi.org>, with environments `testpypi-core`
   (for `openpipeline-core`) and `testpypi` (for `openpipeline`), create those two
   environments in GitHub, then run the Release workflow by hand from
   `main` (Actions > Release > Run workflow) with "testpypi" ticked. Check
   `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ openpipeline==0.1.0`.
4. Run `python3 scripts/bump_version.py --check 0.1.0`. It should print nothing.
5. In `CHANGELOG.md`, fold the Unreleased section into the `0.1.0` section, give it
   today's date, and leave an empty Unreleased section.
6. Run `make lint typecheck test build docs-build`. Install the built wheels in a
   fresh virtual environment and run `openpipeline demo --no-serve` to confirm the
   example ships inside them.
7. Tag and push: `git tag v0.1.0 && git push origin main v0.1.0`.
8. Approve the `pypi-core` and `pypi` environments when GitHub asks. Wait for the PyPI, Docker, and
   GitHub release jobs to finish.
9. Make the GHCR package public if this is the first image.
10. Try it from scratch: `pip install openpipeline==0.1.0` and `openpipeline demo`,
    then `docker run --rm -p 8484:8484 ghcr.io/pawanpatil19/openpipeline:0.1.0`.
11. Check that https://openpipeline.vercel.app/ (the landing page, `/docs/`, and
    `/demo/`) is live and that the pull request action works with `@v0.1.0`.

## Website (Vercel)

The website at https://openpipeline.vercel.app/ deploys from `main` through Vercel's
Git integration. Every push to `main` is a production deploy, and every pull request
gets a preview deploy. It is one static site:

- `/` is the landing page in `site/`.
- `/docs/` is the mkdocs site.
- `/demo/` is a read-only copy of the web UI. `scripts/export_demo.py` writes the
  demo project's API answers as JSON files that the UI reads instead of a server.

`scripts/build_site.sh` builds all three into `build/site`, and `make site` runs it
locally. The `Site` workflow runs the same script on pull requests.

One-time setup: in Vercel, choose Add New > Project, import this repository, and leave
Root Directory at the repository root. Everything else comes from `vercel.json`. If the
project gets a different production domain, set `VERCEL_PROJECT_PRODUCTION_URL` (Vercel
sets it for you) and update the links in `README.md`.
