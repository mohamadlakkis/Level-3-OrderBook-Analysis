# Automated pull-request checks

## Summary
Every PR runs an automated tests to prevent errors from being merged into `master`. 
This README explains that it is advisable to run the checks locally before pushing, this way you can fix any errors before the PR is created. [PLUS I added another rule that before being able to merge you must have the most recent version of the master branch, this is to avoid conflicts and make sure you are not merging an old version of the code] [Plus I added a rule that two approvals are required before merging, this is to make sure that at least two people have reviewed the code and are satisfied with it]

## Description

[workflows/ci.yml](workflows/ci.yml) runs the test suite, Ruff lint checks, and
strict mypy type checks for every pull request. It also runs after pushes to
`master`, and can be started manually from the Actions tab[On github].


## Understanding the Test Workflow
Each run checks out the proposed changes, selects Python 3.10, and installs the
exact dependencies in `uv.lock` using `uv sync --locked --group dev`. The explicit
development group installs pytest, Ruff, and mypy. An inconsistent lockfile is a
failure, not an automatic lockfile update. Dependency downloads are cached between
runs. Tests generate small synthetic ITCH files; CI does not download Nasdaq data
or convert the full daily source.

The workflow's `Python checks` job fails if installation or any check fails.
It also requires download-script tests to pass on native macOS and Windows.
Those jobs use a tiny local HTTP fixture and do not download Nasdaq data or
install project dependencies. The final `Python checks` gate runs even if a
dependency fails and explicitly reports failure, preserving the required status
name configured in your ruleset. Platform commands are at the top of each script
in [setup_scripts/](../setup_scripts/).
The read-only repository permission is sufficient for testing. Concurrent runs
for the same PR are cancelled when a newer commit arrives, and a ten-minute
timeout prevents a stuck job from running indefinitely.

## Running the Checks Locally[Recommended]
To run the same checks locally:

```bash
uv sync --locked --group dev
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked mypy
```

GitHub-hosted execution is verified after pushing; local checks do not execute
the checkout/setup actions or change branch protection.
