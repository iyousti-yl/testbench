"""Lineage: which objects a connection holds, which objects read from which, and what changed.

A connector with the ``lineage`` capability returns a ``LineageGraph``. Each capture is stored
as a snapshot; comparing it with the previous snapshot gives the objects that were added,
changed or removed since then, the objects downstream of each change, and the scenarios that
read any of them, so you know what to re-test.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from testbench.scenario import Suite

SNAPSHOT_ID = re.compile(r"^[0-9]{8}T[0-9]{12}Z$")
KEEP_SNAPSHOTS = 50
STATUSES = ("added", "changed", "removed")


@dataclass
class LineageObject:
    schema: str
    name: str
    kind: str  # "view", "table", "virtual table", ... or "external" (outside the scope)
    columns: list[str] = field(default_factory=list)  # "NAME TYPE" in position order
    definition: str = ""  # view SQL, when the system exposes it
    created_at: str = ""

    @property
    def key(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name

    @property
    def fingerprint(self) -> str:
        payload = json.dumps([self.kind, self.columns, _normalize_sql(self.definition)])
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class LineageEdge:
    source: str  # key of the object that is read
    target: str  # key of the object that reads it


@dataclass
class LineageGraph:
    objects: dict[str, LineageObject] = field(default_factory=dict)
    edges: list[LineageEdge] = field(default_factory=list)

    def add(self, obj: LineageObject) -> None:
        self.objects[obj.key] = obj

    def upstream(self, key: str) -> list[str]:
        return sorted({e.source for e in self.edges if e.target == key})

    def downstream(self, key: str) -> list[str]:
        return sorted({e.target for e in self.edges if e.source == key})

    def impacted(self, keys: set[str]) -> list[str]:
        """Everything that reads, directly or indirectly, from any of ``keys``."""
        seen: set[str] = set()
        todo = list(keys)
        while todo:
            for target in self.downstream(todo.pop()):
                if target not in seen and target not in keys:
                    seen.add(target)
                    todo.append(target)
        return sorted(seen)

    def to_json(self) -> dict[str, Any]:
        return {
            "objects": [asdict(o) for o in self.objects.values()],
            "edges": [asdict(e) for e in self.edges],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LineageGraph:
        graph = cls(edges=[LineageEdge(**e) for e in data.get("edges", [])])
        for raw in data.get("objects", []):
            graph.add(LineageObject(**raw))
        return graph


@dataclass
class LineageSnapshot:
    id: str
    connection: str
    captured_at: str
    scope: list[str]
    graph: LineageGraph

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "connection": self.connection,
            "captured_at": self.captured_at,
            "scope": self.scope,
            "graph": self.graph.to_json(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LineageSnapshot:
        return cls(
            id=data["id"],
            connection=data["connection"],
            captured_at=data["captured_at"],
            scope=list(data.get("scope", [])),
            graph=LineageGraph.from_json(data["graph"]),
        )


@dataclass
class Change:
    key: str
    status: str  # "added", "changed" or "removed"
    kind: str
    details: list[str] = field(default_factory=list)
    definition_diff: str = ""
    impacted: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)  # "suite/scenario-id"


@dataclass
class LineageDiff:
    previous: LineageSnapshot | None
    changes: list[Change] = field(default_factory=list)
    edges_added: list[LineageEdge] = field(default_factory=list)
    edges_removed: list[LineageEdge] = field(default_factory=list)

    @property
    def first(self) -> bool:
        return self.previous is None

    def scenarios(self) -> list[str]:
        return sorted({s for c in self.changes for s in c.scenarios})

    def counts(self) -> list[tuple[str, int]]:
        """How many objects were added, changed and removed, leaving out zeros."""
        found = [(s, sum(c.status == s for c in self.changes)) for s in STATUSES]
        return [(s, n) for s, n in found if n]


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.split())


def _column_details(old: LineageObject, new: LineageObject) -> list[str]:
    def by_name(columns: list[str]) -> dict[str, str]:
        return {c.split(" ", 1)[0]: c for c in columns}

    before, after = by_name(old.columns), by_name(new.columns)
    details = []
    added = [n for n in after if n not in before]
    removed = [n for n in before if n not in after]
    retyped = [n for n in after if n in before and after[n] != before[n]]
    if added:
        details.append("columns added: " + ", ".join(added))
    if removed:
        details.append("columns removed: " + ", ".join(removed))
    if retyped:
        details.append(
            "column types changed: "
            + ", ".join(f"{before[n]} -> {after[n].split(' ', 1)[-1]}" for n in retyped)
        )
    if not (added or removed or retyped) and list(before) != list(after):
        details.append("column order changed")
    return details


def _definition_diff(old: LineageObject, new: LineageObject) -> str:
    if _normalize_sql(old.definition) == _normalize_sql(new.definition):
        return ""
    lines = difflib.unified_diff(
        old.definition.splitlines(),
        new.definition.splitlines(),
        fromfile="previous",
        tofile="current",
        lineterm="",
    )
    return "\n".join(lines)


def compare(
    previous: LineageSnapshot | None,
    current: LineageSnapshot,
    suites: list[Suite] | None = None,
) -> LineageDiff:
    diff = LineageDiff(previous=previous)
    if previous is None:
        return diff
    old, new = previous.graph, current.graph
    for key in sorted(set(old.objects) | set(new.objects)):
        before, after = old.objects.get(key), new.objects.get(key)
        if before is None and after is not None:
            if after.kind != "external":
                diff.changes.append(Change(key, "added", after.kind))
        elif after is None and before is not None:
            if before.kind != "external":
                diff.changes.append(Change(key, "removed", before.kind))
        elif before is not None and after is not None and before.fingerprint != after.fingerprint:
            change = Change(key, "changed", after.kind, _column_details(before, after))
            change.definition_diff = _definition_diff(before, after)
            if change.definition_diff:
                change.details.insert(0, "definition changed")
            if before.kind != after.kind:
                change.details.insert(0, f"was a {before.kind}")
            diff.changes.append(change)
    old_edges, new_edges = set(old.edges), set(new.edges)
    diff.edges_added = sorted(new_edges - old_edges, key=lambda e: (e.target, e.source))
    diff.edges_removed = sorted(old_edges - new_edges, key=lambda e: (e.target, e.source))
    for change in diff.changes:
        graph = old if change.status == "removed" else new
        change.impacted = graph.impacted({change.key})
        names = [change.key, *change.impacted]
        objects = {**old.objects, **new.objects}
        change.scenarios = scenarios_reading(
            [objects[k].name for k in names if k in objects], current.connection, suites or []
        )
    return diff


def _mentions(query: str, name: str) -> bool:
    pattern = rf"(?<![A-Za-z0-9_$#]){re.escape(name)}(?![A-Za-z0-9_$#])"
    return re.search(pattern, query, re.IGNORECASE) is not None


def scenarios_reading(names: list[str], connection: str, suites: list[Suite]) -> list[str]:
    """Scenarios with a query on ``connection`` that mentions any of the object names."""
    found = []
    for suite in suites:
        for scenario in suite.scenarios:
            queries = []
            if scenario.select and scenario.connection == connection:
                queries.append(scenario.select)
            for check in scenario.checks:
                if (check.connection or scenario.connection) == connection:
                    queries.append(check.query)
                reconcile = check.expect.get("reconcile")
                if isinstance(reconcile, dict):
                    if reconcile.get("connection", scenario.connection) == connection:
                        queries.append(str(reconcile.get("query", "")))
            if any(_mentions(q, n) for q in queries for n in names):
                found.append(f"{suite.name}/{scenario.id}")
    return found


def snapshot_time(snapshot_id: str) -> str:
    """ISO time of a snapshot id (``20261011T171233123456Z``)."""
    moment = datetime.strptime(snapshot_id[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    return moment.isoformat(timespec="seconds")


class LineageStore:
    """Snapshots live under ``<output_dir>/lineage/<connection>/<id>.json``."""

    def __init__(self, output_dir: Path) -> None:
        self.root = output_dir / "lineage"

    def _folder(self, connection: str) -> Path:
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", connection):
            raise ValueError(f"invalid connection name {connection!r}")
        return self.root / connection

    def ids(self, connection: str) -> list[str]:
        folder = self._folder(connection)
        if not folder.is_dir():
            return []
        return sorted(p.stem for p in folder.glob("*.json") if SNAPSHOT_ID.match(p.stem))

    def load(self, connection: str, snapshot_id: str) -> LineageSnapshot | None:
        if not SNAPSHOT_ID.match(snapshot_id):
            return None
        path = self._folder(connection) / f"{snapshot_id}.json"
        if not path.is_file():
            return None
        return LineageSnapshot.from_json(json.loads(path.read_text(encoding="utf-8")))

    def latest(self, connection: str) -> LineageSnapshot | None:
        ids = self.ids(connection)
        return self.load(connection, ids[-1]) if ids else None

    def previous(self, connection: str, snapshot_id: str) -> LineageSnapshot | None:
        earlier = [i for i in self.ids(connection) if i < snapshot_id]
        return self.load(connection, earlier[-1]) if earlier else None

    def save(self, snapshot: LineageSnapshot) -> Path:
        folder = self._folder(snapshot.connection)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{snapshot.id}.json"
        path.write_text(json.dumps(snapshot.to_json(), indent=1), encoding="utf-8")
        for old in self.ids(snapshot.connection)[:-KEEP_SNAPSHOTS]:
            (folder / f"{old}.json").unlink(missing_ok=True)
        return path


def capture(connector: Any, connection: str, scope: list[str] | None = None) -> LineageSnapshot:
    """Read the graph from a connector that has the ``lineage`` capability."""
    if "lineage" not in getattr(connector, "capabilities", ()):
        raise ValueError(f"connection '{connection}' cannot provide lineage")
    graph, used_scope = connector.lineage(scope)
    now = datetime.now(timezone.utc)
    return LineageSnapshot(
        id=now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond:06d}Z",
        connection=connection,
        captured_at=now.isoformat(timespec="seconds"),
        scope=used_scope,
        graph=graph,
    )
