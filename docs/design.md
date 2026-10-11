# Testbench design note (v1)

Status: agreed direction, updated with milestone 1 · 2026-10-11 · "Testbench" is a working name.

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
    name: str  # "datasphere", "sqlite", ...
    capabilities: set[str]  # {"sql", "metadata", "write"}

    def test_connection(self) -> None: ...
    def list_objects(self, scope: str | None = None) -> list[ObjectRef]: ...
    def describe(self, obj: ObjectRef) -> ObjectSchema: ...  # columns, types, keys
    def query(self, sql: str, params: dict | None = None) -> Table: ...
    def close(self) -> None: ...
```

- `Table` is a light in-memory table (columns + rows) so the core does not depend on any one database library.
- Connectors are discovered through Python entry points (`testbench.connectors`), so a connector can also ship as a separate package later.
- **Datasphere connector:** SQL over the HANA protocol (`hdbcli`, TLS only) using a space's database user with read access. It reads the views the space exposes for consumption; `schema` (the space id) becomes the current schema so scenarios can use unqualified view names. Object metadata comes from `SYS.VIEWS`, `SYS.TABLES` and their column views. The Datasphere CLI is an optional extra for later.
- **Read-only guard:** the runner refuses any statement that is not a single `SELECT` (or `WITH`) before it reaches a connector. This prevents mistakes; the real protection is a database user with read privileges only.
- **SQLite connector:** used for the demo and for automated tests, so everything runs without an SAP tenant.

## Scenario format

A scenario is a fixed structure defined by a JSON Schema: [`src/testbench/schema/scenario.schema.json`](../src/testbench/schema/scenario.schema.json). Files can be written as JSON or YAML (same structure). The engine only executes this structure; it never interprets free text.

The intended flow is: a consultant writes the **requirement** in business language, the `write-scenario` skill (`.claude/skills/write-scenario/SKILL.md`, later an in-app assistant) translates it into the structure using the real column names of the views involved, and a person reviews the generated queries before the scenario is used. The requirement is kept verbatim in the file so every report shows it next to its result.

```yaml
version: 1
scenario: Employee with two contracts in the same month
requirement: >
  When an employee changes contract mid-month, payroll must receive one cost line per contract.
tags: [payroll, edge-case]
connection: datasphere_dev

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

Expectations in v1 (one or more per check, under `expect`):

- `row_count`: exact number, or `{min, max}`
- `all_rows`: a simple expression every row must satisfy, for example `fte > 0 and fte <= 1` (a small safe language: columns, arithmetic, comparisons, `and`/`or`/`not`, `in`, `abs`, `round`)
- `equals`: expected rows inline or from a CSV file next to the scenario
- `regression`: compare with the stored baseline on key columns, with a numeric tolerance
- `reconcile`: compare with another query, usually on another connection (source versus target), on key columns with a tolerance

A scenario whose `select` finds no records is reported as **not tested**, never as passed.

## How scenarios get their data

1. **Selection (v1 default).** The scenario finds real records that match it (`select:` above) and checks the output for those records. Works with read-only access, which is all most clients allow.
2. **Fixtures (later).** The scenario writes synthetic input rows into a test space, runs the flow and checks the output. More powerful, but needs write access and a way to trigger Datasphere flows.

v1 builds option 1 and keeps the interface open for option 2.

## Security and privacy

Data security is a top priority: clients will connect HR and finance data. The rules below hold from the first version, even while the product is a demo.

- **Workspaces isolate clients.** Every client case (NMBS first) lives in its own workspace with its own connections, scenarios, baselines and reports. In the web app, access is checked on the server for every request, and a user only sees workspaces they are a member of. There is no global view across workspaces.
- **Login is required** for the web app. No page or API returns workspace data to an anonymous request.
- **Credentials** are never stored in scenario files or the repository. The CLI reads them from environment variables (`${VAR}` in `testbench.yaml`); the web app will store them encrypted and never show them back.
- **Read-only access.** Connectors only read. The SQLite connector opens databases read-only; the Datasphere connector will use a database user with read privileges only.
- **Hash-mode baselines.** For connections marked `sensitive: true`, baselines store one hash per row and totals per numeric column, so regressions are detected without keeping personal data. Reports of failing checks do show sample rows (up to 20), because a report must show what broke; they are stored inside the workspace and protected by the same access control.
- **Synthetic data only** in development, tests and demos. Real client data never enters the repository.

## Web app

A FastAPI app with server-rendered pages and no JavaScript (`testbench web serve`).

- **Data layout:** `TESTBENCH_DATA_DIR/app.db` holds users, workspaces, memberships and encrypted secrets. Each workspace has its own folder (`workspaces/<id>/`) with the same layout as a CLI project, so the engine runs unchanged.
- **Access control:** every workspace route resolves the workspace with a query that joins the signed-in user's memberships. A workspace the user is not a member of answers 404, exactly like one that does not exist.
- **Sessions:** signed, HTTP-only, SameSite=Lax cookies, valid 8 hours; a new session on every login; CSRF tokens on every form; 5 failed logins lock an email address for 15 minutes.
- **Passwords:** scrypt hashes; at least 12 characters.
- **Connection secrets:** encrypted with a key derived from `TESTBENCH_SECRET_KEY`, passed to the runner only at run time, never rendered.
- **Headers:** a strict Content-Security-Policy (no scripts at all), no framing, `nosniff`, `no-store` caching. Reports are served with their own CSP and shown in a sandboxed frame.
- **Accounts** are created by an administrator on the command line for now. Self-service invitations and single sign-on (Microsoft Entra ID or SAP Cloud Identity) come later.

## Command line

```
testbench init [dir]               # create an example project with synthetic demo data
testbench connections              # test every configured connection
testbench objects <connection>     # list tables and views (add --columns for columns)
testbench validate [suite]         # check scenario files against the schema
testbench list                     # list suites and scenarios
testbench baseline <suite>         # capture or refresh baselines
testbench run <suite> [--tag x]    # run checks, write an HTML report, exit 1 on failure
testbench demo break|fix           # inject or remove defects in the demo data
```

The exit code makes it usable in CI or after a transport.

## Milestones

1. Core engine, scenario schema, SQLite connector, HTML report, synthetic HR demo suite. (done)
2. Web app with login and workspaces: browse suites, run them, read reports. (done)
3. NMBS demo workspace on synthetic SuccessFactors data, reachable only after login. (first version: `testbench web seed-demo`)
4. Skill that translates a business requirement into a scenario file. (done: `.claude/skills/write-scenario`)
5. Datasphere connector. (built and tested against a simulated driver; still to verify on a real tenant)

## Open questions

- Can a Datasphere database user read views that are not exposed for consumption? If not, which views must a client expose for good coverage?
- Is a free or trial Datasphere tenant available for development?
