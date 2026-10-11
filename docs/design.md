# Testbench design note (v1)

Status: agreed direction, updated with milestone 6 · 2026-10-11 · "Testbench" is a working name.

## Goal

Let SAP data consultants define business test scenarios in plain, readable files, run them against any data platform after each change, and see clearly what broke. Datasphere is the first connector; the core knows nothing about Datasphere.

## Core concepts

| Concept | Meaning |
| --- | --- |
| Connector | A plug-in that talks to one kind of system (SAP Datasphere and SAP SuccessFactors today; later BW/4HANA, SAC, CPI). |
| Connection | A configured instance of a connector (tenant, space, user). In the web app it belongs to a workspace and its secrets are stored encrypted; on the command line secrets come from environment variables. Never from files in the repo. |
| Suite | A folder of scenarios that belong together, for example `nmbs-hr-integration`. |
| Scenario | One business case to test, written in YAML. |
| Check | One verifiable expectation inside a scenario. |
| Baseline | A stored snapshot of an object's output, used to detect regressions. |
| Run | One execution of a suite, with a result per check and an HTML report. |

## Connector interface

Every connector implements the same small interface, so adding a system never touches the core:

```python
class Connector(Protocol):
    name: str  # "datasphere", "successfactors", ...
    capabilities: set[str]  # {"sql" or "odata", "metadata"}

    def test_connection(self) -> None: ...
    def list_objects(self, scope: str | None = None) -> list[ObjectRef]: ...
    def describe(self, obj: ObjectRef) -> ObjectSchema: ...  # columns, types, keys
    def query(self, query: str, params: dict | None = None) -> Table: ...  # SQL or OData path
    def close(self) -> None: ...
```

- `Table` is a light in-memory table (columns + rows) so the core does not depend on any one database library.
- Connectors are discovered through Python entry points (`testbench.connectors`), so a connector can also ship as a separate package later.
- **Offered in the web app** when the connector also declares `title`, `description` and `settings_fields` (a list of `SettingField`: label, help, whether it is secret, whether it is shown on the connection card), and optionally `check_settings(settings)` to validate and normalise what was typed. The web app builds its forms and connection cards from these, so it contains no connector-specific code. Today that list is SAP Datasphere and SAP SuccessFactors.
- **Datasphere connector:** SQL over the HANA protocol (`hdbcli`, TLS only) using a space's database user with read access. It reads the views the space exposes for consumption; `space` becomes the current schema so scenarios can use unqualified view names. Object metadata comes from `SYS.VIEWS`, `SYS.TABLES` and their column views. Settings: tenant URL (shown, not used to connect), space ID, database host, user and password.
- **SuccessFactors connector:** OData v2 over HTTPS with only GET requests. A query is an OData path such as `EmpJob?$select=userId,startDate&$filter=...`; only `$select`, `$filter`, `$expand`, `$orderby`, `$top`, `$skip`, `fromDate`, `toDate` and `asOfDate` are accepted. Pages are followed through `__next` (same host only), values are converted with the entity's `$metadata` types (dates, decimals, integers), and expanded navigation properties become `nav/field` columns. `describe` returns the `sap:label` business names. Authentication is OAuth 2.0 with a SAML bearer assertion that Testbench signs locally (RSA-SHA256, exclusive canonical XML), or basic authentication while SAP still allows it.
- **Read-only guard:** for SQL connectors the runner refuses any statement that is not a single `SELECT` (or `WITH`) before it reaches the connector. This prevents mistakes; the real protection is a database user with read privileges only. OData connectors only send GET requests.
- **SQLite connector:** used for automated tests only, so everything runs without an SAP tenant. It is never offered in the web app, because it would let a user read files on the server.

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
- **Credentials** are never stored in scenario files or the repository. The CLI reads them from environment variables (`${VAR}` in `testbench.yaml`); the web app stores them encrypted, never shows them back, and keeps a stored password when a form leaves it empty. Values typed into the web app are never expanded as `${VAR}`, so a form cannot read the server's environment.
- **Connections only reach SAP.** In the web app, Datasphere connections must use a SAP HANA Cloud host (`*.hanacloud.ondemand.com`) and SuccessFactors connections a SuccessFactors API server, so a connection form cannot be used to reach other hosts from the server. The SuccessFactors connector never follows redirects and refuses next-page links to another host.
- **Read-only access.** Connectors only read. The SQLite connector opens databases read-only; the Datasphere connector uses a database user with read privileges only; the SuccessFactors connector only sends GET requests.
- **Hash-mode baselines.** For connections marked `sensitive: true`, baselines store one hash per row and totals per numeric column, so regressions are detected without keeping personal data. Reports of failing checks do show sample rows (up to 20), because a report must show what broke; they are stored inside the workspace and protected by the same access control.
- **Synthetic data only** in development, tests and demos. Real client data never enters the repository.

## Web app

A FastAPI app with server-rendered pages and no JavaScript (`testbench web serve`).

- **Data layout:** `TESTBENCH_DATA_DIR/app.db` holds users, workspaces, memberships, connections and their encrypted secrets (schema versioned with `PRAGMA user_version`). Each workspace has its own folder (`workspaces/<id>/`) with `suites/` and `.testbench/` (baselines and runs); the runner gets its connections from the database, so the engine runs unchanged.
- **Workspaces:** any signed-in user can create one and becomes its owner. The id in links is derived from the name once and never changes on rename, and an id whose folder still exists on disk is never reused. Deleting asks to type the id, removes the folder first and then the database rows, so no data is left behind for a later workspace.
- **Roles:** members can open a workspace, write and run scenarios and test connections. Only owners rename or delete the workspace and add, edit or delete connections (403 for members).
- **Scenario editor:** create, edit and delete scenarios in the app. A scenario stays a file in the workspace folder (`suites/<suite>/<id>.yaml`), so the engine, the command line and the skill share it. Every save is checked against the scenario schema, unique check names, the workspace's connections and (for `select`) a SQL connection before anything is written; files are replaced atomically under the workspace lock. The file name is derived from the title once and never changes; deleting a scenario also deletes its baselines, a new scenario never inherits baselines left under its name, and a suite whose last scenario is deleted is removed. A suite or a single scenario can be run or baselined from the app.
- **Access control:** every workspace route resolves the workspace with a query that joins the signed-in user's memberships, and every connection lookup is scoped to that workspace. A workspace the user is not a member of answers 404, exactly like one that does not exist.
- **Sessions:** signed, HTTP-only, SameSite=Lax cookies, valid 8 hours; a new session on every login; CSRF tokens on every form; 5 failed logins lock an email address for 15 minutes.
- **Passwords:** scrypt hashes; at least 12 characters.
- **Connection secrets:** encrypted with a key derived from `TESTBENCH_SECRET_KEY`, passed to the runner only at run time, never rendered.
- **Headers:** a strict Content-Security-Policy (no scripts at all), no framing, `nosniff`, `no-store` caching. Reports are served with their own CSP and shown in a sandboxed frame.
- **Accounts** are created by an administrator on the command line for now (`testbench web create-user`, `add-member`). Self-service invitations and single sign-on (Microsoft Entra ID or SAP Cloud Identity) come later.

## Command line

```
testbench init [dir]               # create an empty project with connection templates
testbench connections              # test every configured connection
testbench objects <connection>     # list tables, views or entities (--match text, --columns)
testbench validate [suite]         # check scenario files against the schema
testbench list                     # list suites and scenarios
testbench baseline <suite>         # capture or refresh baselines
testbench run <suite> [--tag x]    # run checks, write an HTML report, exit 1 on failure
```

The exit code makes it usable in CI or after a transport.

## Milestones

1. Core engine, scenario schema, SQLite connector, HTML report. (done)
2. Web app with login and workspaces: browse suites, run them, read reports. (done)
3. Workspaces and connections managed in the app, with no built-in demo data. (done)
4. Skill that translates a business requirement into a scenario file. (done: `.claude/skills/write-scenario`)
5. Datasphere and SuccessFactors connectors. (built and tested against simulated systems; still to verify on a real tenant)
6. Create, edit and delete test scenarios in the app. (done)
7. Lineage of the tenant's objects, with change detection between runs. (planned)

## Open questions

- Can a Datasphere database user read views that are not exposed for consumption? If not, which views must a client expose for good coverage?
- Is a free or trial Datasphere tenant available for development?
