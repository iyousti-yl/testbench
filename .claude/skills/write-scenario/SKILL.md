---
name: write-scenario
description: Translate a business requirement (in plain language, any of English, Dutch or French) into a Testbench scenario file that follows the scenario JSON Schema, validate it and dry-run it. Use when someone describes a rule, edge case, regression or reconciliation they want tested.
---

# Write a Testbench scenario from a business requirement

The engine only executes the fixed structure in `src/testbench/schema/scenario.schema.json`. Your job is the translation: business words in, a valid, reviewed scenario file out. A wrong translation gives false confidence, so never guess and always hand the result to a person for review.

## Inputs to collect

- **The requirement**, in the person's own words. Keep it verbatim; it goes into `requirement`.
- **The Testbench project** (the folder with `testbench.yaml`) and the **suite** to add to. If not given, list suites with `testbench list` and pick the one that matches the subject; say which.
- **The connection(s)** involved. Read them from `testbench.yaml`.

## Steps

1. **Read the contract.** Read `src/testbench/schema/scenario.schema.json` and one or two existing scenarios in the suite, so the file matches the house style.

2. **Find the real objects and columns.** Run `testbench objects <connection> --columns` and pick the tables or views the requirement talks about. Never invent a column name. If the requirement uses a business term (for example "cost line" or "contract change") that maps to more than one candidate, ask one short question with the candidates, or pick the most likely one and write the assumption in `description`.

3. **Choose the pattern** that fits the requirement:

   | The requirement says... | Use |
   | --- | --- |
   | "when X happens, then Y" (an edge case) | `select` finds the records where X happens; checks use `{{ selection }}` and assert Y |
   | "always", "every", "never" (a rule on all rows) | a query plus `all_rows`, or a query for the violations plus `row_count: 0` |
   | "must not change", "same as before" | `regression` with the business key as `keys` and a small `tolerance` for amounts |
   | "must match", "must equal the source" | `reconcile` against the other connection, on the shared key, with a `tolerance` |
   | a known expected result | `equals` with the expected rows inline (or a CSV file next to the scenario) |

   Prefer a query that returns the **violations** (rows that break the rule) with `row_count: 0`: the report then lists exactly the records to fix.

4. **Write the file** as `<suite folder>/<kebab-case-name>.json`:
   - `version: 1`, a short `scenario` title in business language, the verbatim `requirement`.
   - `description`: how you translated it, every assumption, and anything the reviewer must confirm.
   - `tags`: the business area plus the pattern (`edge-case`, `regression`, `reconciliation`, `data-quality`).
   - Check `name`s in business language ("one cost line per contract"), not SQL.
   - SQL: `SELECT` only, in the connection's dialect. Quote identifiers the way that system needs (Datasphere/HANA: `"VIEW_NAME"`). Aggregate amounts with `ROUND(..., 2)` before comparing.
   - One scenario per business rule. Split a requirement that contains several rules.

5. **Validate and dry-run.**
   - `testbench validate <suite>` must pass. Fix any schema error it names.
   - `testbench run <suite> --scenario <file name without extension>`.
   - If the result is **Not tested**, the `select` found no matching records: say so, and suggest either a wider selection or test data.
   - If it fails, check whether the failure is a real finding or a translation mistake before reporting it.
   - A `regression` check needs a baseline first: `testbench baseline <suite> --scenario <name>` on a known-good state.

6. **Hand it over for review.** Reply with: the file path; each check in one plain sentence ("finds employees with two contracts in one month and checks each has two cost lines"); the dry-run result; and the assumptions to confirm. The scenario is only trusted after a person confirms the queries match the requirement.

## Rules

- Synthetic data only in this repository. Never paste real client records, employee data, hostnames or credentials into a scenario, a description or a commit.
- Never write to a connected system. Only `SELECT` statements.
- Do not change the schema to make a scenario fit. If the requirement needs something the schema cannot express, say so and propose the schema change separately.
