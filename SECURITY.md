# Security policy

## Supported versions

The current <code>main</code> branch and the latest tagged release receive security fixes. Research snapshots are immutable evidence; fixes to their tooling are released in a new snapshot rather than rewriting a tagged one.

## Reporting a vulnerability

Use [GitHub's private vulnerability reporting](https://github.com/decentralizedblack-maker/sge-coding-agents/security/advisories/new) for credential exposure, unsafe command handling, path traversal, artifact-isolation failures, or other security-sensitive findings.

Do not open a public issue containing secrets, private traces, exploit payloads against third-party services, or identifying benchmark/evaluator material. A non-sensitive public issue is appropriate for ordinary correctness bugs.

The maintainers will acknowledge a private report, reproduce it when safe, assess affected versions, and coordinate a fix and disclosure. This research release does not run tools on a user's behalf; any future executor integration must add an explicit sandbox, resource, cancellation, verification, and rollback threat model.
