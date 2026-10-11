"""Synthetic HR demo: a SuccessFactors-like source and a Datasphere-like target in SQLite.

All names and numbers are generated. No real data is used.
"""

from __future__ import annotations

import random
import shutil
import sqlite3
from importlib.resources import as_file, files
from pathlib import Path

SOURCE_DB = "demo/sf_source.db"
TARGET_DB = "demo/datasphere.db"
MONTHS = [f"2026-{m:02d}" for m in range(1, 7)]
COST_CENTERS = ["CC-1000-OPS", "CC-2000-IT", "CC-3000-FIN", "CC-4000-HR"]

_CONTRACTS_DDL = """
CREATE TABLE {name} (
  contract_id TEXT NOT NULL,
  employee_id TEXT NOT NULL,
  month TEXT NOT NULL,
  share REAL NOT NULL,          -- part of the month this contract covers
  fte REAL NOT NULL,
  cost_center TEXT,
  monthly_salary REAL NOT NULL,
  PRIMARY KEY (contract_id, month)
)
"""

_GOOD_COST_LINES = """
CREATE VIEW HR_COST_LINES_V AS
SELECT contract_id, employee_id, month, cost_center, share,
       ROUND(monthly_salary * fte * share, 2) AS cost
FROM HR_CONTRACTS
"""

# The defect: someone "deduplicated" per employee and month, which silently drops
# the first contract when an employee changes contract mid-month.
_BROKEN_COST_LINES = """
CREATE VIEW HR_COST_LINES_V AS
SELECT contract_id, employee_id, month, cost_center, share,
       ROUND(monthly_salary * fte * share, 2) AS cost
FROM HR_CONTRACTS c
WHERE contract_id = (
  SELECT MAX(contract_id) FROM HR_CONTRACTS c2
  WHERE c2.employee_id = c.employee_id AND c2.month = c.month
)
"""

_PAYROLL_EXPORT = """
CREATE VIEW PAYROLL_EXPORT_V AS
SELECT employee_id, month, ROUND(SUM(cost), 2) AS total_cost
FROM HR_COST_LINES_V
GROUP BY employee_id, month
"""


def generate_contracts(seed: int = 42, employees: int = 40) -> list[tuple]:
    rng = random.Random(seed)
    rows: list[tuple] = []
    contract_no = 1000
    for e in range(1, employees + 1):
        employee_id = f"E{e:04d}"
        contract_no += 1
        contract = f"C{contract_no}"
        fte = rng.choice([1.0, 1.0, 1.0, 0.8, 0.5])
        salary = float(rng.randrange(3200, 7200, 50))
        cost_center = rng.choice(COST_CENTERS)
        change_month = rng.choice(MONTHS[1:]) if rng.random() < 0.25 else None
        for month in MONTHS:
            if month == change_month:
                share = rng.choice([0.25, 0.5, 0.75])
                rows.append((contract, employee_id, month, share, fte, cost_center, salary))
                contract_no += 1
                contract = f"C{contract_no}"
                fte = rng.choice([1.0, 0.8])
                salary = round(salary * rng.choice([1.03, 1.05, 1.1]), -1)
                cost_center = rng.choice(COST_CENTERS)
                rows.append((contract, employee_id, month, 1 - share, fte, cost_center, salary))
            else:
                rows.append((contract, employee_id, month, 1.0, fte, cost_center, salary))
    return rows


def build(project_dir: Path) -> None:
    rows = generate_contracts()
    for rel, table in ((SOURCE_DB, "SF_CONTRACTS"), (TARGET_DB, "HR_CONTRACTS")):
        path = project_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        db = sqlite3.connect(path)
        try:
            db.execute(_CONTRACTS_DDL.format(name=table))
            db.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
            if table == "HR_CONTRACTS":
                db.execute(_GOOD_COST_LINES)
                db.execute(_PAYROLL_EXPORT)
            db.commit()
        finally:
            db.close()


def set_broken(project_dir: Path, broken: bool) -> None:
    """Introduce (or remove) a logic defect and a data anomaly in the target."""
    path = project_dir / TARGET_DB
    if not path.exists():
        raise FileNotFoundError(f"demo database not found: {path} (run 'testbench init')")
    db = sqlite3.connect(path)
    try:
        db.execute("DROP VIEW PAYROLL_EXPORT_V")
        db.execute("DROP VIEW HR_COST_LINES_V")
        db.execute(_BROKEN_COST_LINES if broken else _GOOD_COST_LINES)
        db.execute(_PAYROLL_EXPORT)
        # The anomaly: a contract that arrived without a cost center.
        first = db.execute(
            "SELECT contract_id, month FROM HR_CONTRACTS ORDER BY contract_id, month LIMIT 1"
        ).fetchone()
        if broken:
            db.execute(
                "UPDATE HR_CONTRACTS SET cost_center = NULL WHERE contract_id = ? AND month = ?",
                first,
            )
        else:
            source = sqlite3.connect(project_dir / SOURCE_DB)
            original = source.execute(
                "SELECT cost_center FROM SF_CONTRACTS WHERE contract_id = ? AND month = ?", first
            ).fetchone()
            source.close()
            db.execute(
                "UPDATE HR_CONTRACTS SET cost_center = ? WHERE contract_id = ? AND month = ?",
                (original[0], *first),
            )
        db.commit()
    finally:
        db.close()


def create_example_project(project_dir: Path) -> None:
    """Copy the example project (config + suite) and build its demo databases."""
    project_dir.mkdir(parents=True, exist_ok=True)
    if (project_dir / "testbench.yaml").exists():
        raise FileExistsError(f"{project_dir / 'testbench.yaml'} already exists")
    with as_file(files("testbench").joinpath("example")) as example:
        shutil.copytree(example, project_dir, dirs_exist_ok=True)
    build(project_dir)
