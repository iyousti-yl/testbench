# Testbench

Business-scenario regression testing for SAP data landscapes. Datasphere is the first connector; the core must never depend on Datasphere or any other single system.

## Read first

- `docs/design.md` is the source of truth for concepts (connector, suite, scenario, check, baseline, run) and the YAML format. Update it in the same PR when a change alters the design.

## Rules

- **Synthetic data only.** Never commit real client data (NMBS, SuccessFactors, HR records), client hostnames, credentials or tenant names. Demo and test data is generated.
- **Connectors are plug-ins.** New systems implement the `Connector` protocol in `src/testbench/connectors/base.py` and register through the `testbench.connectors` entry point. No connector-specific logic in the core.
- **Secrets come from environment variables** (`${VAR}` in `testbench.yaml`), never from files in the repo.
- **Sensitive connections store baselines in hash mode** so personal data is not persisted.
- Keep runtime dependencies minimal. Database drivers are optional extras (for example `pip install testbench[datasphere]`).

## Skills

- `write-scenario`: turn a business requirement into a scenario file, validate it and dry-run it. Use it whenever someone describes something they want tested.

## Development flow

- `main` always works. Every change goes through a branch and a pull request; CI (ruff + pytest) must be green before merge.
- Setup: `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`
- Checks: `ruff check . && ruff format --check . && pytest`
