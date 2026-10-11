# Testbench

Business-scenario regression testing for SAP data landscapes, starting with SAP Datasphere.

Consultants describe test scenarios in a fixed, readable format (JSON or YAML), run them against any connected system after each change, and get a clear report of what broke. Each scenario keeps the original business requirement next to its result.

## Try the demo

The demo uses generated HR data: a SuccessFactors-like source and a Datasphere-like target, both in SQLite.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .

testbench init demo && cd demo
testbench baseline hr-payroll   # capture the known-good state
testbench run hr-payroll        # all 4 scenarios pass

testbench demo break            # inject a logic defect and a data anomaly
testbench run hr-payroll        # all 4 scenarios fail, with details in the HTML report
testbench demo fix
```

The demo suite covers four kinds of test:

| Scenario | What it shows |
| --- | --- |
| Employee with two contracts in the same month | A business edge case, tested on the real records that match it |
| Cost lines unchanged after a change | Regression against a baseline (stored as hashes, because the connection is sensitive) |
| Payroll export matches SuccessFactors | Reconciliation between two systems |
| Contract data is complete and plausible | Data-quality rules (written in JSON) |

## Run the web app

The web app puts each client case in its own workspace. Users sign in and only see the workspaces they are members of.

```bash
pip install -e ".[web]"
export TESTBENCH_DATA_DIR=./testbench-data
export TESTBENCH_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')

testbench web seed-demo                    # NMBS demo + a second workspace, two users
testbench web serve --insecure-cookies     # http://127.0.0.1:8000 (plain HTTP: local use only)
```

`seed-demo` prints two accounts once. Sign in with the NMBS one: you can run the suite, inject a defect and read the report, and the other workspace answers "page does not exist".

Other admin commands: `testbench web create-user`, `create-workspace [--demo]`, `add-member`, `set-secret`. Keep `TESTBENCH_SECRET_KEY` safe and stable: it signs sessions and encrypts stored connection secrets.

## Documentation

- [Design note](docs/design.md): concepts, connector interface, scenario format, security.
- [Scenario schema](src/testbench/schema/scenario.schema.json): the fixed structure every scenario follows.

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check . && pytest
```
