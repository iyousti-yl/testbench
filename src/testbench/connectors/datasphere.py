"""SAP Datasphere connector: SQL over the HANA protocol with a space's database user.

Setup in Datasphere: Space Management > Database Access > create a database user with
"Enable Read Access (SQL)". It reads the views the space exposes for consumption.
Install the driver with ``pip install 'testbench[datasphere]'``.

Settings in ``testbench.yaml`` (the web app asks for the same fields)::

    datasphere_dev:
      type: datasphere
      tenant_url: https://<tenant>.<region>.hcs.cloud.sap   # shown in the app, not used to connect
      space: HR_SPACE            # the space id; queries can then use unqualified view names
      host: ${DSP_HOST}          # <id>.hana.prod-<region>.hanacloud.ondemand.com
      user: ${DSP_USER}          # <SPACE_ID>#<SUFFIX>
      password: ${DSP_PASSWORD}
      sensitive: true
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from testbench.connectors.base import (
    ColumnInfo,
    ConnectorError,
    ObjectRef,
    ObjectSchema,
    SettingField,
    ensure_read_only,
)
from testbench.lineage import LineageEdge, LineageGraph, LineageObject
from testbench.table import Table

_LIST_OBJECTS = """
SELECT SCHEMA_NAME, VIEW_NAME AS NAME, 'view' AS KIND FROM SYS.VIEWS WHERE SCHEMA_NAME = ?
UNION ALL
SELECT SCHEMA_NAME, TABLE_NAME AS NAME, 'table' AS KIND FROM SYS.TABLES WHERE SCHEMA_NAME = ?
ORDER BY 2
"""

_DESCRIBE = """
SELECT COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE, POSITION FROM SYS.{source}
WHERE SCHEMA_NAME = ? AND {name_column} = ?
ORDER BY POSITION
"""

_PRIMARY_KEY = """
SELECT COLUMN_NAME FROM SYS.CONSTRAINTS
WHERE SCHEMA_NAME = ? AND TABLE_NAME = ? AND IS_PRIMARY_KEY = 'TRUE'
"""


# The web app only connects to SAP HANA Cloud, the database under every Datasphere tenant,
# so a connection form can never be used to reach other hosts from the server.
HOST_SUFFIXES = (".hanacloud.ondemand.com",)
_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_SPACE_ID = re.compile(r"^[A-Z0-9_]{1,64}$")
_SCHEMA = re.compile(r"^[A-Z0-9_][A-Z0-9_#$]{0,126}$")  # spaces and Open SQL schemas


def tenant_url(value: str) -> str:
    """``https://host`` from whatever was pasted (a bookmark, a deep link, a bare host)."""
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not _HOSTNAME.match(host):
        raise ConnectorError("tenant URL must look like https://<tenant>.<region>.hcs.cloud.sap")
    return f"https://{host}"


def database_host(value: str) -> str:
    value = value.strip().lower()
    host = urlsplit(value if "://" in value else "//" + value).hostname or ""
    if not _HOSTNAME.match(host) or not host.endswith(HOST_SUFFIXES):
        raise ConnectorError(
            "database host must be the SAP HANA Cloud host of the tenant, "
            "for example <id>.hana.prod-eu10.hanacloud.ondemand.com"
        )
    return host


def parse_scope(value: str | list[str]) -> list[str]:
    """Space IDs or schema names, from a list or a text separated by commas or spaces."""
    names = value if isinstance(value, list) else re.split(r"[,\s]+", value or "")
    scope = []
    for name in (str(n).strip().upper() for n in names):
        if not name or name in scope:
            continue
        if not _SCHEMA.match(name):
            raise ConnectorError(f"'{name}' is not a space ID or schema name")
        scope.append(name)
    return scope


# Lineage reads the catalog of the schemas in scope. The aliases keep the statements apart.
_LINEAGE_VIEWS = """
SELECT LINEAGE_VIEWS.SCHEMA_NAME, LINEAGE_VIEWS.VIEW_NAME, LINEAGE_VIEWS.DEFINITION,
       LINEAGE_VIEWS.CREATE_TIME
FROM SYS.VIEWS AS LINEAGE_VIEWS WHERE LINEAGE_VIEWS.SCHEMA_NAME IN ({schemas})
"""
_LINEAGE_TABLES = """
SELECT LINEAGE_TABLES.SCHEMA_NAME, LINEAGE_TABLES.TABLE_NAME, LINEAGE_TABLES.TABLE_TYPE,
       LINEAGE_TABLES.CREATE_TIME
FROM SYS.TABLES AS LINEAGE_TABLES WHERE LINEAGE_TABLES.SCHEMA_NAME IN ({schemas})
"""
_LINEAGE_COLUMNS = """
SELECT SCHEMA_NAME, VIEW_NAME AS OBJECT_NAME, COLUMN_NAME, DATA_TYPE_NAME, LENGTH, SCALE, POSITION
FROM SYS.VIEW_COLUMNS AS LINEAGE_COLUMNS WHERE SCHEMA_NAME IN ({schemas})
UNION ALL
SELECT SCHEMA_NAME, TABLE_NAME, COLUMN_NAME, DATA_TYPE_NAME, LENGTH, SCALE, POSITION
FROM SYS.TABLE_COLUMNS WHERE SCHEMA_NAME IN ({schemas})
ORDER BY 1, 2, 7
"""
_LINEAGE_DEPENDENCIES = """
SELECT BASE_SCHEMA_NAME, BASE_OBJECT_NAME, BASE_OBJECT_TYPE,
       DEPENDENT_SCHEMA_NAME, DEPENDENT_OBJECT_NAME
FROM SYS.OBJECT_DEPENDENCIES AS LINEAGE_DEPENDENCIES
WHERE DEPENDENT_SCHEMA_NAME IN ({schemas}) AND DEPENDENCY_TYPE = 1
"""


def _text(value: Any) -> str:
    """LOB columns (view definitions) come back as objects with ``read()``."""
    if value is None:
        return ""
    if hasattr(value, "read"):
        value = value.read()
    return value.decode() if isinstance(value, bytes) else str(value)


def _column(name: str, dtype: str, length: Any, scale: Any) -> str:
    size = ""
    if length not in (None, "") and dtype.upper() in {"NVARCHAR", "VARCHAR", "DECIMAL", "CHAR"}:
        size = f"({length}" + (f",{scale}" if scale not in (None, "") else "") + ")"
    return f"{name} {dtype}{size}"


def _load_driver() -> Any:
    try:
        from hdbcli import dbapi
    except ImportError as exc:
        raise ConnectorError(
            "the Datasphere connector needs SAP's HANA client: pip install 'testbench[datasphere]'"
        ) from exc
    return dbapi


class DatasphereConnector:
    name = "datasphere"
    title = "SAP Datasphere"
    description = "Views and tables of a space, read over SQL"
    capabilities = frozenset({"sql", "metadata", "lineage"})
    settings_fields = (
        SettingField(
            "tenant_url",
            "Tenant URL",
            help="The address you open Datasphere with in the browser.",
            placeholder="https://your-tenant.eu10.hcs.cloud.sap",
            kind="url",
            summary=True,
        ),
        SettingField(
            "space",
            "Space ID",
            help="The technical ID of the space, as shown in Space Management.",
            placeholder="HR_INTEGRATION",
            summary=True,
        ),
        SettingField(
            "host",
            "Database host",
            help="Space Management > Database Access > your database user > Host Name.",
            placeholder="xxxxxxxx-xxxx.hana.prod-eu10.hanacloud.ondemand.com",
            group="Database user",
        ),
        SettingField(
            "user",
            "Database user",
            help="A database user of this space with read access (SQL), named SPACE#SUFFIX.",
            placeholder="HR_INTEGRATION#TESTBENCH",
            summary=True,
            group="Database user",
        ),
        SettingField(
            "password",
            "Password",
            kind="password",
            secret=True,
            group="Database user",
        ),
        SettingField(
            "lineage_scope",
            "Spaces or schemas to map",
            help=(
                "Leave empty to map this space. List more spaces or Open SQL schemas, separated"
                " by commas, to map them together; other spaces need a database analysis user."
            ),
            placeholder="HR_INTEGRATION, FINANCE",
            required=False,
            group="Lineage",
        ),
    )

    @staticmethod
    def check_settings(settings: dict[str, str]) -> dict[str, str]:
        space = settings.get("space", "").strip().upper()
        if not _SPACE_ID.match(space):
            raise ConnectorError("space ID may only contain letters, digits and underscores")
        user = settings.get("user", "").strip()
        if not user:
            raise ConnectorError("database user is required")
        scope = parse_scope(settings.get("lineage_scope", ""))
        return {
            **settings,
            "tenant_url": tenant_url(settings.get("tenant_url", "")),
            "space": space,
            "host": database_host(settings.get("host", "")),
            "user": user,
            "lineage_scope": ", ".join(scope),
        }

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        space: str | None = None,
        schema: str | None = None,
        port: int | str = 443,
        validate_certificate: bool = True,
        timeout_seconds: int | str = 300,
        connect_timeout_seconds: int | str = 20,
        lineage_scope: str | list[str] = "",
        **_: Any,
    ) -> None:
        if not host or not user or not password:
            raise ConnectorError("datasphere connection needs host, user and password")
        self.host = host
        self.port = int(port)
        self.user = user
        self._password = password
        self.schema = space or schema  # "schema" is the older name of the setting
        self.validate_certificate = validate_certificate
        self.timeout_ms = int(timeout_seconds) * 1000
        self.connect_timeout_ms = int(connect_timeout_seconds) * 1000
        self.lineage_scope = parse_scope(lineage_scope)
        self._dbapi = _load_driver()
        self._conn: Any = None

    def __repr__(self) -> str:  # never include the password
        return (
            f"DatasphereConnector(host={self.host!r}, user={self.user!r}, schema={self.schema!r})"
        )

    def _connection(self) -> Any:
        if self._conn is None:
            dbapi = self._dbapi
            properties: dict[str, Any] = {
                "encrypt": True,  # Datasphere only accepts TLS connections
                "sslValidateCertificate": self.validate_certificate,
                "communicationTimeout": self.timeout_ms,
                "connectTimeout": self.connect_timeout_ms,
            }
            if self.schema:
                properties["currentSchema"] = self.schema
            try:
                self._conn = dbapi.connect(
                    address=self.host,
                    port=self.port,
                    user=self.user,
                    password=self._password,
                    **properties,
                )
            except dbapi.Error as exc:
                raise ConnectorError(f"cannot connect to Datasphere at {self.host}: {exc}") from exc
        return self._conn

    def _execute(self, sql: str, params: Any = None) -> Table:
        conn = self._connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params) if params is not None else cursor.execute(sql)
            columns = [d[0] for d in cursor.description or []]
            return Table(columns=columns, rows=cursor.fetchall())
        except Exception as exc:  # the driver raises dbapi.Error subclasses
            raise ConnectorError(str(exc)) from exc
        finally:
            cursor.close()

    def test_connection(self) -> None:
        self._execute("SELECT 1 FROM DUMMY")

    def _schema_for(self, scope: str | None) -> str:
        schema = scope or self.schema
        if not schema:
            raise ConnectorError("set 'space' (the space ID) or pass a scope")
        return schema

    def list_objects(self, scope: str | None = None) -> list[ObjectRef]:
        schema = self._schema_for(scope)
        table = self._execute(_LIST_OBJECTS, (schema, schema))
        return [ObjectRef(name=name, kind=kind, schema=s) for s, name, kind in table.rows]

    def describe(self, obj: ObjectRef) -> ObjectSchema:
        schema = obj.schema or self._schema_for(None)
        if obj.kind == "table":
            source, name_column = "TABLE_COLUMNS", "TABLE_NAME"
        else:
            source, name_column = "VIEW_COLUMNS", "VIEW_NAME"
        sql = _DESCRIBE.format(source=source, name_column=name_column)
        info = self._execute(sql, (schema, obj.name))
        if not info.rows:
            raise ConnectorError(f"object not found: {schema}.{obj.name}")
        keys: set[str] = set()
        if obj.kind == "table":
            keys = {row[0] for row in self._execute(_PRIMARY_KEY, (schema, obj.name)).rows}
        columns = [
            ColumnInfo(name=name, type=dtype, nullable=nullable == "TRUE", key=name in keys)
            for name, dtype, nullable, _ in info.rows
        ]
        return ObjectSchema(ref=obj, columns=columns)

    def query(self, sql: str, params: dict[str, Any] | None = None) -> Table:
        ensure_read_only(sql)
        return self._execute(sql, params)

    def lineage(self, scope: list[str] | None = None) -> tuple[LineageGraph, list[str]]:
        """Views and tables of the schemas in scope (default: the ``lineage_scope`` setting,
        else the space), with their columns, view definitions and which object reads which.
        Objects outside the scope that are read appear as ``external``."""
        chosen = scope or self.lineage_scope or [self._schema_for(None)]
        schemas = sorted({s.strip() for s in chosen if s.strip()})
        marks = ", ".join("?" for _ in schemas)
        params = tuple(schemas)
        graph = LineageGraph()
        for schema, name, definition, created in self._execute(
            _LINEAGE_VIEWS.format(schemas=marks), params
        ).rows:
            graph.add(
                LineageObject(schema, name, "view", [], _text(definition), str(created or ""))
            )
        for schema, name, table_type, created in self._execute(
            _LINEAGE_TABLES.format(schemas=marks), params
        ).rows:
            kind = "virtual table" if str(table_type or "").upper() == "VIRTUAL" else "table"
            graph.add(LineageObject(schema, name, kind, [], "", str(created or "")))
        columns = self._execute(_LINEAGE_COLUMNS.format(schemas=marks), params + params)
        for schema, name, column, dtype, length, scale, _ in columns.rows:
            obj = graph.objects.get(f"{schema}.{name}")
            if obj is not None:
                obj.columns.append(_column(column, str(dtype), length, scale))
        dependencies = self._execute(_LINEAGE_DEPENDENCIES.format(schemas=marks), params)
        edges = set()
        for base_schema, base_name, base_type, schema, name in dependencies.rows:
            source = f"{base_schema}.{base_name}"
            if source not in graph.objects:
                kind = "external" if base_schema not in schemas else str(base_type).lower()
                graph.add(LineageObject(base_schema, base_name, kind))
            edges.add(LineageEdge(source=source, target=f"{schema}.{name}"))
        graph.edges = sorted(edges, key=lambda e: (e.target, e.source))
        return graph, schemas

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
