# Testbench

Business-scenario regression testing for SAP data landscapes, starting with SAP Datasphere.

Consultants describe test scenarios in a fixed, readable format (JSON or YAML), run them against any connected system after each change, and get a clear report of what broke. Each scenario keeps the original business requirement next to its result.

## Run the web app

The web app puts each client case in its own workspace. Users sign in and only see the workspaces they are members of.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[web,datasphere]"
export TESTBENCH_DATA_DIR=./testbench-data
export TESTBENCH_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')

testbench web create-user you@example.com --name "Your Name"   # asks for a password
testbench web serve --insecure-cookies     # http://127.0.0.1:8000 (plain HTTP: local use only)
```

After signing in:

1. **Create a workspace** for a client or project. Rename or delete it under **Settings**; deleting removes its connections, scenarios, baselines and reports. Until the first test run, the workspace shows the three steps to get started.
2. **Add connections.** The app offers SAP Datasphere and SAP SuccessFactors. Each connection card shows where it points (Datasphere: tenant URL, space and database user; SuccessFactors: API server, company ID and user) and whether the last test succeeded. Passwords and keys are encrypted and never shown again. Edit or delete a connection from its edit page.
3. **Write test scenarios.** Each scenario has a title, the business requirement in plain words, a connection, optional "records to test" and one or more checks written in YAML. The app validates every save against the scenario format and keeps scenarios as files in the workspace, so the command line and the `write-scenario` skill work on the same files. Run a whole suite or a single scenario, capture baselines and read the report. Every scenario shows its latest result, and each suite a health strip with one segment per scenario.
4. **Map the lineage** of a Datasphere connection: every view and table in the space, its columns and definition, and which object reads which. Update it after a change and the app shows only what changed since the last lineage (added, changed or removed objects, column and definition differences), what sits downstream of each change and which scenarios to re-run.
5. Only workspace owners change the workspace and its connections; every member can write and run scenarios. Give a colleague access with `testbench web add-member <workspace-id> <email> [--role owner]`.

Keep `TESTBENCH_SECRET_KEY` safe and stable: it signs sessions and encrypts stored credentials. A hosted instance can run on Render's free plan: see [docs/deploy.md](docs/deploy.md).

## Connectors

### SAP Datasphere

In Datasphere, open Space Management > Database Access and create a database user for the space with read access (SQL). In the app you need the tenant URL, the space ID, and the database user's host name, user name and password. The app only connects to SAP HANA Cloud hosts (`*.hanacloud.ondemand.com`). Install the driver with `pip install -e ".[datasphere]"`.

Lineage maps the connection's space by default. To map several spaces together, list them under "Spaces or schemas to map"; reading other spaces needs a database analysis user instead of a space user.

### SAP SuccessFactors

Reads OData v2 entities (EmpJob, PerPerson, User, ...). A scenario query on a SuccessFactors connection is an OData path instead of SQL:

```yaml
query: EmpJob?$select=userId,startDate,costCenter&$filter=company eq 'ACME_BE'
```

Supported options are `$select`, `$filter`, `$expand`, `$orderby`, `$top`, `$skip` and the effective-dating parameters `fromDate`, `toDate` and `asOfDate`. Every request is a GET; give the API user read permissions only.

Authentication is OAuth 2.0 with a SAML bearer assertion (recommended): register an OAuth client in SuccessFactors with an X.509 certificate and give Testbench the client ID, the user ID to run as and the certificate's private key. Testbench signs the assertion itself, so the key never leaves the server. User name and password also work while SAP still allows them.

### On the command line

The same connectors work from `testbench.yaml`, with secrets in environment variables. `testbench init` writes an empty project with commented templates for both; `testbench connections` tests them, `testbench objects <connection> --match EmpJob --columns` lists objects and columns, and `testbench lineage <connection>` maps lineage and prints what changed since the last run.

## From business requirement to test

Describe what you want tested in plain language to Claude Code in this repository, for example *"Every employee with a contract in a month must appear in the payroll export for that month"*. The `write-scenario` skill finds the real tables and columns, writes a scenario that follows the schema, validates it, dry-runs it and explains each check so you can review it.

## Documentation

- [Design note](docs/design.md): concepts, connector interface, scenario format, lineage, security.
- [Scenario schema](src/testbench/schema/scenario.schema.json): the fixed structure every scenario follows.
- [DESIGN.md](DESIGN.md) and [PRODUCT.md](PRODUCT.md): the app's visual system and who it is for.

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check . && pytest
```
