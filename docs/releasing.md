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

## One-time setup

These need a repository admin and only have to be done once.

- **PyPI trusted publishing.** On PyPI, add a "pending publisher" for both
  `openpipeline` and `openpipeline-core`: owner `PawanPatil19`, repository
  `openpipeline`, workflow `release.yml`, environment `pypi`. No API token is
  stored in GitHub.
- **GitHub environment.** Create an environment named `pypi` under
  Settings → Environments. Adding yourself as a required reviewer gives every
  release a final manual approval.
- **GHCR visibility.** After the first image is pushed, make the package public
  under the repository's Packages settings.
- **GitHub Pages.** The docs site is deployed by the docs workflow. In the
  repository, go to Settings → Pages → Source and choose **GitHub Actions**. The
  first push to `main` after that publishes the site at
  https://pawanpatil19.github.io/openpipeline/.
- **Branch protection.** Require the `All checks passed` status on `main`.
