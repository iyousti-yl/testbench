# Testbench design note (v1)

Status: draft for Issam's approval · 2026-10-11 · "Testbench" is a working name.

## Goal

Let SAP data consultants define business test scenarios in plain, readable files, run them against any data platform after each change, and see clearly what broke. Datasphere is the first connector; the core knows nothing about Datasphere.

## Core concepts

| Concept | Meaning |
| --- | --- |
| Connector | A plug-in that talks to one kind of system (Datasphere, SQLite, Postgres, later BW/4HANA, SAC, CPI). |
| Connection | A configured instance of a connector (host, user, space). Secrets come from environment variables, never from files in the repo. |
| Suite | A folder of scenarios that belong together, for example `nmbs-hr-integration`. |
| Scenario | One business case to test, written in YAML. |
| Check | One verifiable expectation inside a scenario. |
| Baseline | A stored snapshot of an object's output, used to detect regressions. |
| Run | One execution of a suite, with a result per check and an HTML report. |

## Connector interface

Every connector implements the same small interface, so adding a system never touches the core:

```python
class Connector(Protocol):
    name: str                                   # "datasphere", "sqlite", ...
    capabilities: set[str]                      # {"sql", "metadata", "write"}

    def test_connection(self) -> None: ...
    def list_objects(self, scope: str | None = None) -> list[ObjectRef]: ...
    def describe(self, obj: ObjectRef) -> ObjectSchema: ...      # columns, types, keys
    def query(self, sql: str, params: dict | None = None) -> Table: ...
```

- `Table` is a light in-memory table (columns + rows) so the core does not depend on any one database library.
- Connectors are discovered through Python entry points (`testbench.connectors`), so a connector can also ship as a separate package later.
- **Datasphere connector:** SQL over the HANA protocol (`hdbcli`) using a Datasphere database user on the space's Open SQL schema. It can read views that are exposed for consumption. Object metadata comes from the same SQL access first; the Datasphere CLI is an optional extra.
- **SQLite connector:** used for the demo and for automated tests, so everything runs without an SAP tenant.

## Scenario format

```yaml
scenario: Employee with two contracts in the same month
tags: [payroll, edge-case]
connection: datasphere_dev
description: >
  An employee who changes contract mid-month must produce one cost line per contract.

select: |                       # which real records represent this scenario
  SELECT employee_id, month
  FROM "HR_CONTRACTS_V"
  GROUP BY employee_id, month
  HAVING COUNT(*) = 2

checks:
  - name: one cost line per contract
    query: |
      SELECT employee_id, month, COUNT(*) AS lines
      FROM "HR_COST_LINES_V"
      WHERE (employee_id, month) IN ({{ selection }})
      GROUP BY employee_id, month
    expect:
      all_rows: "lines == 2"

  - name: no missing cost center
    query: SELECT * FROM "HR_COST_LINES_V" WHERE cost_center IS NULL
    expect:
      row_count: 0
```

Check types in v1:

- `row_count` (exact, min, max)
- `all_rows` (a simple expression that every row must satisfy)
- `equals` (expected rows inline or from a CSV file)
- `regression` (compare to the stored baseline on key columns, with a numeric tolerance)
- `reconcile` (compare the same measure across two connections, for example source and target)

## Decision needed: how scenarios get their data

1. **Selection (v1 default).** The scenario finds real records that match it (`select:` above) and checks the output for those records. Works with read-only access, which is all most clients allow.
2. **Fixtures (later).** The scenario writes synthetic input rows into a test space, runs the flow and checks the output. More powerful, but needs write access and a way to trigger Datasphere flows.

v1 builds option 1 and keeps the interface open for option 2.

## Privacy

HR data is personal data. Baselines can be stored in **hash mode**: one hash per row plus totals per numeric column, so a regression is detected without keeping the personal data itself. Hash mode is the default for any connection marked `sensitive: true`. Development uses synthetic data only.

## Command line

```
testbench init                     # create a project folder with an example suite
testbench connections test         # check every configured connection
testbench baseline <suite>         # capture or refresh baselines
testbench run <suite> [--tag x]    # run checks, write an HTML report, exit 1 on failure
```

The exit code makes it usable in CI or after a transport.

## Milestones

1. Core engine, YAML format, SQLite connector, HTML report, demo suite.
2. Datasphere connector, tested against Issam's trial tenant.
3. NMBS-style suite on synthetic SuccessFactors data (contracts, cost lines, CPI output reconciliation).
4. Simple web UI to browse suites, run them and read reports.

## Open questions

- Can a Datasphere database user read views that are not exposed for consumption? If not, which views must a client expose for good coverage?
- Is a free or trial Datasphere tenant available for development?
