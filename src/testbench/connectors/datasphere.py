"""SAP Datasphere connector: SQL over the HANA protocol with a space's database user.

Setup in Datasphere: Space Management > Database Access > create a database user with
"Enable Read Access (SQL)". It reads the views the space exposes for consumption.
Install the driver with ``pip install 'testbench[datasphere]'``.

Settings in ``testbench.yaml``::

    datasphere_dev:
      type: datasphere
      host: ${DSP_HOST}          # <tenant>.hana.prod-<region>.hanacloud.ondemand.com
      user: ${DSP_USER}          # <SPACE_ID>#<SUFFIX>
      password: ${DSP_PASSWORD}  # or stored encrypted in the web app
      schema: HR_SPACE           # the space id; queries can then use unqualified view names
      sensitive: true
"""

from __future__ import annotations

from typing import Any

from testbench.connectors.base import (
    ColumnInfo,
    ConnectorError,
    ObjectRef,
    ObjectSchema,
    ensure_read_only,
)
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
    capabilities = frozenset({"sql", "metadata"})

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        schema: str | None = None,
        port: int | str = 443,
        validate_certificate: bool = True,
        timeout_seconds: int | str = 300,
        **_: Any,
    ) -> None:
        if not host or not user or not password:
            raise ConnectorError("datasphere connection needs host, user and password")
        self.host = host
        self.port = int(port)
        self.user = user
        self._password = password
        self.schema = schema
        self.validate_certificate = validate_certificate
        self.timeout_ms = int(timeout_seconds) * 1000
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
            raise ConnectorError("set 'schema' (the space id) or pass a scope")
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

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
