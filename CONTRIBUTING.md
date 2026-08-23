# Contributing

Thank you for helping make SGE more reproducible and easier to evaluate.

## Good contribution areas

- Graph-model correctness and adversarial tests
- Trace-schema robustness
- Scheduling and admission-policy baselines
- Reproduction portability
- Evidence provenance and statistical checks
- Documentation that sharpens claim boundaries

Live provider adapters and production executors need a separate design discussion before implementation because they add credential, side-effect, isolation, and rollback obligations.

## Development setup

~~~bash
git clone https://github.com/Joey-Lei/sge-coding-agents.git
cd sge-coding-agents
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[artifact,dev]"
python3 reproduce.py
python3 -m pytest -q
python3 tools/check_release.py
~~~

## Pull requests

Keep pull requests focused. Describe:

1. the behavior or evidence question being changed;
2. the scientific claim boundary;
3. the checks run and their output;
4. any change to derived evidence or package hashes;
5. privacy, license, and rollback considerations.

Tests should cover the requested behavior and at least one likely adjacent failure. If generated artifact files change, explain why and include the source-to-output provenance update.

## Evidence contributions

Do not commit credentials, raw runtime histories, model reasoning, private prompts, hidden evaluator material, gold patches, reference solutions, account metadata, or unrestricted logs. Derived evidence must have a documented schema, denominator, source lineage, and redistribution basis.

Negative and null results are first-class evidence. Do not remove a failed or invalid case merely because it weakens a headline.

## Claim discipline

Use these terms precisely:

- **structural ceiling** for work/span opportunity over an annotated graph;
- **historical observation** for a result not produced by a prospective locked comparison;
- **end-to-end speedup** only for a valid quality-equivalent prospective pair;
- **invalid** when the protocol gate fails, with formal metrics kept null.

By contributing, you agree that your contribution is licensed under Apache-2.0.
