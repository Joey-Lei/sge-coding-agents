# Third-party and dataset notices

This repository does not vendor third-party source code, Python wheels, benchmark prompts, gold patches, reference solutions, or hidden evaluator assets.

The optional offline figure path installs:

- Matplotlib 3.9.4
- Pillow 11.3.0
- pytest 8.4.2 for development and verification

Those packages remain under their respective licenses. Installing the optional dependencies does not incorporate them into the SGE source distribution.

The frozen artifact contains public repository and SWE-bench-style case identifiers plus sanitized derived numerical evidence. It does not redistribute the underlying task text or evaluator assets. Source snapshots, content hashes, and sanitization mappings are recorded under <code>artifact/reviewer_snapshot/provenance</code>.
