# Reproduction

## Requirements

- Python 3.10 or newer
- A POSIX-like shell for the command examples
- No GPU
- No API key
- No model, benchmark target, or official evaluator access

## Fast API smoke

~~~bash
python3 -m pip install --upgrade pip
python3 -m pip install -e .
sge analyze examples/minimal_workgraph.json --workers 1,2,4
python3 -m pytest -q tests/test_public_api.py
~~~

This path checks the installable graph model and CLI without figure dependencies.

## Full offline artifact

~~~bash
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[artifact,dev]"
python3 reproduce.py
python3 -m pytest -q
~~~

The portable default writes only to a temporary directory. It recomputes and byte-compares the quantitative claims, renders five PDF/PNG figure pairs to scratch space, and validates the untouched sealed artifact and its manifest. This keeps a clean checkout clean across operating systems and font stacks. It uses temporary cache directories for Matplotlib and font configuration.

Expected outputs include:

- <code>artifact/reviewer_snapshot/outputs/recomputed_claims.json</code>
- five PDF and five 300-DPI PNG figures
- twenty accessibility previews
- <code>artifact/reviewer_snapshot/audit/verification_report.json</code>
- <code>artifact/reviewer_snapshot/provenance/artifact_manifest.json</code>
- <code>artifact/reviewer_snapshot/SHA256SUMS</code>

## Maintainer refresh

The committed PDF/PNG bytes and accessibility previews are platform-bound renderings. To intentionally regenerate them and refresh the figure contract, audit records, artifact manifest, and `SHA256SUMS`, run:

~~~bash
python3 reproduce.py --refresh
~~~

Review the resulting diff before committing. Reviewers and CI should use the non-mutating default command.

## Release audit

~~~bash
python3 tools/check_release.py
git diff --exit-code
~~~

The release audit checks required public surfaces, forbidden raw file families, local machine paths, credential-like material, oversized files, local Markdown links, and the frozen artifact manifest. A clean <code>git diff</code> after the default reproduction confirms that the portable path did not mutate tracked outputs.

## Container-free design

The evidence path is small enough to run directly in a virtual environment. A container is intentionally not required, avoiding a second opaque execution surface. Exact Python dependency versions for the figure path are pinned in the package metadata and in the snapshot's environment file.
