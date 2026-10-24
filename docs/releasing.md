# Releasing

Releases are cut by pushing a version tag. The
[release workflow](https://github.com/PawanPatil19/openpipeline/blob/main/.github/workflows/release.yml) then:

1. Checks the tag matches the version in every package.
2. Builds the web UI into the Python package and builds both wheels.
3. Publishes `openpipeline-core` and `openpipeline` to PyPI.
4. Builds and pushes a multi-arch Docker image (amd64 and arm64) to
   `ghcr.io/pawanpatil19/openpipeline`, with an SBOM and provenance.
5. Creates a GitHub release with generated notes and the wheels attached.

Tags with a pre-release suffix (for example `v1.1.0-rc1`) are marked as
pre-releases and do not move the `latest` Docker tag.

## Steps

```bash
python3 scripts/bump_version.py 1.2.3
uv lock
# Move the Unreleased section of CHANGELOG.md under a 1.2.3 heading.
git commit -am "Release 1.2.3"
git tag v1.2.3
git push origin main v1.2.3
```

`bump_version.py` sets the version in both Python packages, in
`apps/web/package.json`, and in the exact `openpipeline-core==` pin of the app.
Never edit those by hand. Check them with
`python3 scripts/bump_version.py --check 1.2.3`. The release workflow runs the
same check against the tag and stops if anything differs.

## One-time setup

These need a repository admin and only have to be done once, before the first tag.

- **PyPI trusted publishing.** On PyPI, add a "pending publisher" for both
  `openpipeline` and `openpipeline-core`: owner `PawanPatil19`, repository
  `openpipeline`, workflow `release.yml`, environment `pypi`. The first release
  creates each project. No API token is stored in GitHub.
- **GitHub environment.** Create an environment named `pypi` under
  Settings > Environments. Adding yourself as a required reviewer gives every
  release a final manual approval.
- **GitHub Pages.** The docs site is deployed by the docs workflow. In the
  repository, go to Settings > Pages > Source and choose **GitHub Actions**. A push
  to `main` that changes `docs/**`, `mkdocs.yml`, `pyproject.toml`, or `uv.lock`
  then publishes the site at https://pawanpatil19.github.io/openpipeline/. GitHub
  creates the `github-pages` environment for you.
- **GHCR visibility.** The first image is pushed as a private package. After it
  appears, make `openpipeline` public under the repository's Packages settings so
  `docker pull ghcr.io/pawanpatil19/openpipeline` works without logging in.
- **Branch protection.** Require the `All checks passed` status on `main`. It
  covers the Python matrix, the web checks, the Docker build, and the PR summary
  action. The docs build runs only when docs files change, so add `Build docs` as a
  required check as well if you want it enforced.

## Cutting 1.0.0

1. Start from an up-to-date `main` with every check green.
2. Confirm the one-time setup above is done. A missing PyPI publisher fails the
   release after the tag is pushed.
3. Run `python3 scripts/bump_version.py --check 1.0.0`. It should print nothing.
4. Check that `CHANGELOG.md` has a `1.0.0` heading and an empty Unreleased section.
5. Run `make lint typecheck test build docs-build`. Install the built wheel in a
   fresh virtual environment and run `openpipeline demo --no-serve` to confirm the
   example ships inside it.
6. Tag and push: `git tag v1.0.0 && git push origin main v1.0.0`.
7. Approve the `pypi` environment when GitHub asks. Wait for the PyPI, Docker, and
   GitHub release jobs to finish.
8. Make the GHCR package public if this is the first image.
9. Try it from scratch: `pip install openpipeline==1.0.0` and `openpipeline demo`,
   then `docker run --rm -p 8484:8484 ghcr.io/pawanpatil19/openpipeline:1.0.0`.
10. Check that https://pawanpatil19.github.io/openpipeline/ is live and that the
    pull request action works with `@v1.0.0`.
