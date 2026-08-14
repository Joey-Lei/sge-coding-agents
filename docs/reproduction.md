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

The artifact writes only beneath <code>artifact/reviewer_snapshot/outputs</code>, <code>artifact/reviewer_snapshot/audit</code>, and its two package-manifest files. It uses temporary cache directories for Matplotlib and font configuration.

Expected outputs include:

- <code>artifact/reviewer_snapshot/outputs/recomputed_claims.json</code>
- five PDF and five 300-DPI PNG figures
- twenty accessibility previews
- <code>artifact/reviewer_snapshot/audit/verification_report.json</code>
- <code>artifact/reviewer_snapshot/provenance/artifact_manifest.json</code>
- <code>artifact/reviewer_snapshot/SHA256SUMS</code>

## Release audit

~~~bash
python3 tools/check_release.py
git diff --exit-code
~~~

The release audit checks required public surfaces, forbidden raw file families, local machine paths, credential-like material, oversized files, local Markdown links, and the frozen artifact manifest. A clean <code>git diff</code> after reproduction confirms deterministic tracked outputs.

## Container-free design

The evidence path is small enough to run directly in a virtual environment. A container is intentionally not required, avoiding a second opaque execution surface. Exact Python dependency versions for the figure path are pinned in the package metadata and in the snapshot's environment file.
