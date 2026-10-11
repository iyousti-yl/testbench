"""SAP SuccessFactors connector: reads OData v2 entities such as EmpJob, PerPerson or User.

Queries are OData paths instead of SQL, for example::

    EmpJob?$select=userId,startDate,costCenter&$filter=company eq 'ACME_BE'

Every request is a GET, so the connector cannot change data. Give the API user read
permissions only.

Authentication:

* ``oauth`` (recommended): OAuth 2.0 with a SAML bearer assertion. Register an OAuth client
  in SuccessFactors (Admin Center > Manage OAuth2 Client Applications) with an X.509
  certificate. Testbench signs the assertion itself with the certificate's private key, so
  the key never leaves this server. Needs ``cryptography`` (``pip install
  'testbench[successfactors]'``).
* ``basic``: user name and password of an API user. SAP is phasing this out.

Settings in ``testbench.yaml`` (the web app asks for the same fields)::

    sf_dev:
      type: successfactors
      api_url: https://api55.sapsf.eu        # the API server of the data center
      company_id: ${SF_COMPANY_ID}
      auth: oauth
      client_id: ${SF_CLIENT_ID}
      user_id: ${SF_USER_ID}
      private_key: ${SF_PRIVATE_KEY}         # PEM
      sensitive: true
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
import secrets
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit

from testbench.connectors.base import (
    ColumnInfo,
    ConnectorError,
    ObjectRef,
    ObjectSchema,
    SettingField,
)
from testbench.table import Table

# API servers of the SuccessFactors data centers. The web app connects nowhere else, so a
# connection form can never be used to reach other hosts from the server.
HOST_SUFFIXES = (
    ".successfactors.com",
    ".successfactors.eu",
    ".successfactors.cn",
    ".sapsf.com",
    ".sapsf.eu",
    ".sapsf.cn",
    ".hr.cloud.sap",
)
_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_COMPANY_ID = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_ENTITY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_DATE = re.compile(r"^/Date\((-?\d+)([+-]\d{4})?\)/$")
# Standard OData query options plus the effective-dating parameters SuccessFactors adds.
_OPTIONS = {
    "$select",
    "$filter",
    "$expand",
    "$orderby",
    "$top",
    "$skip",
    "fromDate",
    "toDate",
    "asOfDate",
}
_NUMBER_TYPES = {"Edm.Decimal", "Edm.Double", "Edm.Single"}
_INTEGER_TYPES = {"Edm.Int16", "Edm.Int32", "Edm.Int64", "Edm.Byte", "Edm.SByte"}
_SAP_NS = "http://www.sap.com/Protocols/SAPData"
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_SAFE = "$,()/:*'"  # kept readable in URLs; everything else is percent-encoded

_SAML_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
_DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
_EXC_C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"


def api_url(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not _HOSTNAME.match(host) or not host.endswith(HOST_SUFFIXES):
        raise ConnectorError(
            "API server URL must be the SuccessFactors API server of your data center, "
            "for example https://api55.sapsf.eu"
        )
    return f"https://{host}"


# HTTP ------------------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: they would carry the Authorization header to another host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect())


def _send(request: urllib.request.Request, timeout: float) -> bytes:
    """One HTTP exchange; tests replace this function."""
    with _opener.open(request, timeout=timeout) as response:
        body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ConnectorError("SuccessFactors response is too large; narrow the query")
    return body


def _error_message(exc: urllib.error.HTTPError) -> str:
    try:
        detail = json.loads(exc.read(65536) or b"{}")
        message = detail.get("error", {}).get("message", {})
        text = message.get("value") if isinstance(message, dict) else str(message)
    except (ValueError, AttributeError, OSError):
        text = None
    if exc.code == 401:
        return "SuccessFactors refused the credentials (401). Check the user and company ID."
    if exc.code == 403:
        return f"the API user has no permission for this (403){': ' + text if text else ''}"
    return f"SuccessFactors answered {exc.code}{': ' + text if text else ''}"


# SAML bearer assertion --------------------------------------------------------------------


def _attr(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace('"', "&quot;")
        .replace("\t", "&#x9;")
        .replace("\n", "&#xA;")
        .replace("\r", "&#xD;")
    )


def _text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def load_private_key(text: str) -> Any:
    """An RSA private key from PEM text, or from the bare base64 SuccessFactors shows."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError as exc:  # pragma: no cover - depends on the installation
        raise ConnectorError(
            "OAuth for SuccessFactors needs cryptography: pip install 'testbench[successfactors]'"
        ) from exc
    text = text.strip()
    if "-----BEGIN" not in text:
        try:
            decoded = base64.b64decode(text, validate=False)
        except ValueError:
            decoded = b""
        if decoded.lstrip().startswith(b"-----BEGIN"):
            text = decoded.decode("ascii", "replace")
    try:
        block = re.search(
            r"-----BEGIN (?:RSA |ENCRYPTED )?PRIVATE KEY-----.*?-----END (?:RSA |ENCRYPTED )?"
            r"PRIVATE KEY-----",
            text,
            re.DOTALL,
        )
        if block:
            key = serialization.load_pem_private_key(block.group(0).encode(), password=None)
        else:
            key = serialization.load_der_private_key(base64.b64decode(text), password=None)
    except (ValueError, TypeError) as exc:
        raise ConnectorError(
            "the private key could not be read; paste the unencrypted PEM key of the "
            "certificate registered for the OAuth client"
        ) from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ConnectorError("the private key must be an RSA key")
    return key


def saml_assertion(
    private_key: Any, client_id: str, user_id: str, token_url: str, now: float | None = None
) -> str:
    """A signed SAML 2.0 bearer assertion for the SuccessFactors token endpoint.

    The XML is written directly in exclusive canonical form (no whitespace between
    elements, explicit end tags, sorted attributes), so the bytes that are digested and
    signed are exactly the bytes that are sent.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    issued = dt.datetime.fromtimestamp(now if now is not None else time.time(), dt.timezone.utc)

    def stamp(delta_minutes: int) -> str:
        moment = issued + dt.timedelta(minutes=delta_minutes)
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    assertion_id = "_" + secrets.token_hex(16)
    head = (
        f'<saml2:Assertion xmlns:saml2="{_SAML_NS}" ID="{assertion_id}" '
        f'IssueInstant="{stamp(0)}" Version="2.0">'
        "<saml2:Issuer>www.successfactors.com</saml2:Issuer>"
    )
    body = (
        "<saml2:Subject>"
        '<saml2:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified">'
        f"{_text(user_id)}</saml2:NameID>"
        '<saml2:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml2:SubjectConfirmationData NotOnOrAfter="{stamp(10)}" '
        f'Recipient="{_attr(token_url)}"></saml2:SubjectConfirmationData>'
        "</saml2:SubjectConfirmation>"
        "</saml2:Subject>"
        f'<saml2:Conditions NotBefore="{stamp(-5)}" NotOnOrAfter="{stamp(10)}">'
        "<saml2:AudienceRestriction>"
        "<saml2:Audience>www.successfactors.com</saml2:Audience>"
        "</saml2:AudienceRestriction>"
        "</saml2:Conditions>"
        f'<saml2:AuthnStatement AuthnInstant="{stamp(0)}" SessionIndex="{assertion_id}">'
        "<saml2:AuthnContext>"
        "<saml2:AuthnContextClassRef>"
        "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"
        "</saml2:AuthnContextClassRef>"
        "</saml2:AuthnContext>"
        "</saml2:AuthnStatement>"
        "<saml2:AttributeStatement>"
        '<saml2:Attribute Name="api_key">'
        f"<saml2:AttributeValue>{_text(client_id)}</saml2:AttributeValue>"
        "</saml2:Attribute>"
        "</saml2:AttributeStatement>"
        "</saml2:Assertion>"
    )
    digest = base64.b64encode(hashlib.sha256((head + body).encode()).digest()).decode()
    signed_info = (
        "<ds:SignedInfo>"
        f'<ds:CanonicalizationMethod Algorithm="{_EXC_C14N}"></ds:CanonicalizationMethod>'
        '<ds:SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256">'
        "</ds:SignatureMethod>"
        f'<ds:Reference URI="#{assertion_id}">'
        "<ds:Transforms>"
        f'<ds:Transform Algorithm="{_DSIG_NS}enveloped-signature"></ds:Transform>'
        f'<ds:Transform Algorithm="{_EXC_C14N}"></ds:Transform>'
        "</ds:Transforms>"
        '<ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"></ds:DigestMethod>'
        f"<ds:DigestValue>{digest}</ds:DigestValue>"
        "</ds:Reference>"
        "</ds:SignedInfo>"
    )
    # Canonicalised on its own, SignedInfo carries the ds namespace it uses.
    canonical_signed_info = signed_info.replace(
        "<ds:SignedInfo>", f'<ds:SignedInfo xmlns:ds="{_DSIG_NS}">', 1
    )
    signature_value = base64.b64encode(
        private_key.sign(canonical_signed_info.encode(), padding.PKCS1v15(), hashes.SHA256())
    ).decode()
    signature = (
        f'<ds:Signature xmlns:ds="{_DSIG_NS}">{signed_info}'
        f"<ds:SignatureValue>{signature_value}</ds:SignatureValue></ds:Signature>"
    )
    return head + signature + body


# Values ----------------------------------------------------------------------------------


def _convert(value: Any, edm_type: str | None) -> Any:
    if isinstance(value, str):
        match = _DATE.match(value)
        if match:
            moment = dt.datetime.fromtimestamp(int(match.group(1)) / 1000, dt.timezone.utc)
            if edm_type == "Edm.DateTimeOffset":
                return moment
            # Edm.DateTime has no time zone; SuccessFactors uses midnight for dates.
            return moment.date() if moment.time() == dt.time(0) else moment.replace(tzinfo=None)
        if edm_type in _NUMBER_TYPES or edm_type in _INTEGER_TYPES:
            try:
                number = Decimal(value)
            except InvalidOperation:
                return value
            return int(number) if edm_type in _INTEGER_TYPES else number
    return value


def _flatten(record: dict[str, Any], types: dict[str, str], prefix: str = "") -> dict[str, Any]:
    """One row from an OData record; expanded navigation properties become ``nav/field``."""
    row: dict[str, Any] = {}
    for key, value in record.items():
        if key == "__metadata":
            continue
        name = prefix + key
        if isinstance(value, dict):
            if "__deferred" in value:
                continue
            if isinstance(value.get("results"), list):
                nested = [_flatten(item, {}, "") for item in value["results"]]
                row[name] = json.dumps(nested, default=str, sort_keys=True)
            else:
                row.update(_flatten(value, {}, name + "/"))
        else:
            row[name] = _convert(value, types.get(name))
    return row


def _parse_query(query: str) -> tuple[str, list[tuple[str, str]]]:
    """``Entity?$select=a,b&$filter=...`` -> ("Entity", [("$select", "a,b"), ...])."""
    # Scenario files may spread a query over several lines.
    text = re.sub(r"\s*\n\s*([?&])", r"\1", query.strip())
    text = re.sub(r"\s*\n\s*", " ", text)
    path, _, options_text = text.partition("?")
    entity = path.strip().strip("/")
    if not _ENTITY.match(entity):
        raise ConnectorError(
            "a SuccessFactors query starts with an entity name, for example "
            "EmpJob?$select=userId,startDate"
        )
    options: list[tuple[str, str]] = []
    for part in filter(None, options_text.split("&")):
        name, _, value = part.partition("=")
        name = unquote(name.strip())
        if name not in _OPTIONS:
            allowed = ", ".join(sorted(_OPTIONS))
            raise ConnectorError(f"query option '{name}' is not supported (use: {allowed})")
        options.append((name, unquote(value.strip())))
    return entity, options


class SuccessFactorsConnector:
    name = "successfactors"
    title = "SAP SuccessFactors"
    description = "OData v2 entities such as EmpJob, PerPerson and User"
    capabilities = frozenset({"odata", "metadata"})
    settings_fields = (
        SettingField(
            "api_url",
            "API server URL",
            help="The API server of your data center, not the URL you log in with.",
            placeholder="https://api55.sapsf.eu",
            kind="url",
            summary=True,
        ),
        SettingField(
            "company_id",
            "Company ID",
            help="In SuccessFactors: your name > Show version information.",
            placeholder="ACMECORPT1",
            summary=True,
        ),
        SettingField(
            "auth",
            "Authentication",
            kind="choice",
            choices=(
                ("oauth", "OAuth 2.0 with a SAML bearer assertion (recommended)"),
                ("basic", "User name and password"),
            ),
            default="oauth",
        ),
        SettingField(
            "client_id",
            "OAuth client ID (API key)",
            help="Admin Center > Manage OAuth2 Client Applications.",
            required=False,
            group="OAuth 2.0",
        ),
        SettingField(
            "user_id",
            "User ID",
            help="The SuccessFactors user the API calls run as. Give it read-only permissions.",
            required=False,
            summary=True,
            group="OAuth 2.0",
        ),
        SettingField(
            "private_key",
            "Private key",
            help="The private key of the certificate registered for the OAuth client (PEM). "
            "Testbench signs with it locally; it is never sent anywhere.",
            kind="textarea",
            required=False,
            secret=True,
            group="OAuth 2.0",
        ),
        SettingField(
            "username",
            "API user name",
            required=False,
            summary=True,
            group="User name and password",
        ),
        SettingField(
            "password",
            "Password",
            kind="password",
            required=False,
            secret=True,
            group="User name and password",
        ),
    )

    @staticmethod
    def check_settings(settings: dict[str, str]) -> dict[str, str]:
        company_id = settings.get("company_id", "").strip()
        if not _COMPANY_ID.match(company_id):
            raise ConnectorError("company ID is required (letters, digits, '.', '_' or '-')")
        auth = settings.get("auth") or "oauth"
        result = {"api_url": api_url(settings.get("api_url", "")), "company_id": company_id}
        if auth == "oauth":
            for key, label in (
                ("client_id", "OAuth client ID"),
                ("user_id", "user ID"),
                ("private_key", "private key"),
            ):
                if not settings.get(key, "").strip():
                    raise ConnectorError(f"{label} is required for OAuth")
            load_private_key(settings["private_key"])
            keys = ("client_id", "user_id", "private_key")
        elif auth == "basic":
            if not settings.get("username", "").strip() or not settings.get("password"):
                raise ConnectorError("user name and password are required")
            keys = ("username", "password")
        else:
            raise ConnectorError("authentication must be 'oauth' or 'basic'")
        result["auth"] = auth
        for key in keys:
            value = settings[key]
            result[key] = value if key in ("password", "private_key") else value.strip()
        return result

    def __init__(
        self,
        api_url: str,
        company_id: str,
        auth: str = "oauth",
        client_id: str = "",
        user_id: str = "",
        private_key: str = "",
        username: str = "",
        password: str = "",
        timeout_seconds: int | str = 60,
        max_rows: int | str = 200_000,
        **_: Any,
    ) -> None:
        if not api_url or not company_id:
            raise ConnectorError("successfactors connection needs api_url and company_id")
        if auth == "oauth" and not (client_id and user_id and private_key):
            raise ConnectorError("OAuth needs client_id, user_id and private_key")
        if auth == "basic" and not (username and password):
            raise ConnectorError("basic authentication needs username and password")
        if auth not in ("oauth", "basic"):
            raise ConnectorError("auth must be 'oauth' or 'basic'")
        self.base_url = api_url.rstrip("/")
        self.host = urlsplit(self.base_url).hostname or ""
        self.company_id = company_id
        self.auth = auth
        self.client_id = client_id
        self.user_id = user_id
        self.username = username
        self._private_key = private_key
        self._password = password
        self.timeout = float(timeout_seconds)
        self.max_rows = int(max_rows)
        self._token: tuple[str, float] | None = None
        self._types: dict[str, dict[str, str]] = {}

    def __repr__(self) -> str:  # never include the password or key
        return (
            f"SuccessFactorsConnector(api_url={self.base_url!r}, "
            f"company_id={self.company_id!r}, auth={self.auth!r})"
        )

    # Requests -----------------------------------------------------------------------------

    def _authorization(self) -> str:
        if self.auth == "basic":
            pair = f"{self.username}@{self.company_id}:{self._password}"
            return "Basic " + base64.b64encode(pair.encode()).decode()
        if self._token is None or self._token[1] < time.monotonic():
            self._token = self._fetch_token()
        return "Bearer " + self._token[0]

    def _fetch_token(self) -> tuple[str, float]:
        token_url = f"{self.base_url}/oauth/token"
        assertion = saml_assertion(
            load_private_key(self._private_key), self.client_id, self.user_id, token_url
        )
        form = urlencode(
            {
                "company_id": self.company_id,
                "client_id": self.client_id,
                "grant_type": "urn:ietf:params:oauth:grant-type:saml2-bearer",
                "assertion": base64.b64encode(assertion.encode()).decode(),
            }
        ).encode()
        request = urllib.request.Request(
            token_url,
            data=form,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = self._json(request, what="sign in")
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise ConnectorError("SuccessFactors did not return an access token")
        lifetime = float(data.get("expires_in") or 3600)
        return token, time.monotonic() + max(lifetime - 120, 60)

    def _json(self, request: urllib.request.Request, what: str) -> Any:
        try:
            body = _send(request, self.timeout)
        except urllib.error.HTTPError as exc:
            if what == "sign in" and exc.code in (400, 401):
                raise ConnectorError(
                    "SuccessFactors refused the OAuth sign-in. Check the client ID, user ID, "
                    "company ID and that the private key matches the registered certificate."
                ) from exc
            raise ConnectorError(_error_message(exc)) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            raise ConnectorError(f"cannot reach SuccessFactors at {self.host}: {reason}") from exc
        except (TimeoutError, OSError) as exc:
            raise ConnectorError(f"cannot reach SuccessFactors at {self.host}: {exc}") from exc
        if what == "metadata":
            return body
        try:
            return json.loads(body)
        except ValueError as exc:
            raise ConnectorError("SuccessFactors did not answer with JSON") from exc

    def _get(self, url: str, what: str = "data") -> Any:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != self.host:
            raise ConnectorError("SuccessFactors pointed to another host; stopped")
        if not parts.path.startswith("/odata/v2/"):
            raise ConnectorError("SuccessFactors pointed outside the OData API; stopped")
        headers = {"Authorization": self._authorization()}
        if what != "metadata":
            headers["Accept"] = "application/json"
        return self._json(urllib.request.Request(url, headers=headers), what)

    def _url(self, entity: str, options: list[tuple[str, str]]) -> str:
        query = "&".join(
            f"{quote(name, safe='$')}={quote(value, safe=_SAFE)}"
            for name, value in [*options, ("$format", "json")]
        )
        return f"{self.base_url}/odata/v2/{entity}?{query}"

    # Connector protocol -------------------------------------------------------------------

    def test_connection(self) -> None:
        self._get(f"{self.base_url}/odata/v2/?$format=json")

    def list_objects(self, scope: str | None = None) -> list[ObjectRef]:
        data = self._get(f"{self.base_url}/odata/v2/?$format=json")
        names = (data.get("d") or {}).get("EntitySets", []) if isinstance(data, dict) else []
        return [ObjectRef(name=name, kind="entity") for name in sorted(names)]

    def describe(self, obj: ObjectRef) -> ObjectSchema:
        if not _ENTITY.match(obj.name):
            raise ConnectorError(f"not an entity name: {obj.name}")
        body = self._get(f"{self.base_url}/odata/v2/{obj.name}/$metadata", what="metadata")
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise ConnectorError(f"could not read the metadata of {obj.name}") from exc
        entity_types = {el.get("Name"): el for el in root.iter() if el.tag.endswith("}EntityType")}
        type_name = obj.name
        for el in root.iter():
            if el.tag.endswith("}EntitySet") and el.get("Name") == obj.name:
                type_name = (el.get("EntityType") or obj.name).rsplit(".", 1)[-1]
        entity_type = entity_types.get(type_name)
        if entity_type is None:
            raise ConnectorError(f"entity not found: {obj.name}")
        keys = {
            ref.get("Name")
            for key in entity_type
            if key.tag.endswith("}Key")
            for ref in key
            if ref.tag.endswith("}PropertyRef")
        }
        columns = [
            ColumnInfo(
                name=prop.get("Name", ""),
                type=prop.get("Type", ""),
                nullable=prop.get("Nullable", "true") != "false",
                key=prop.get("Name") in keys,
                label=prop.get(f"{{{_SAP_NS}}}label", ""),
            )
            for prop in entity_type
            if prop.tag.endswith("}Property")
        ]
        return ObjectSchema(ref=ObjectRef(obj.name, kind="entity"), columns=columns)

    def _property_types(self, entity: str) -> dict[str, str]:
        if entity not in self._types:
            try:
                schema = self.describe(ObjectRef(entity, kind="entity"))
                self._types[entity] = {c.name: c.type for c in schema.columns}
            except ConnectorError:
                self._types[entity] = {}  # values stay as SuccessFactors sends them
        return self._types[entity]

    def query(self, sql: str, params: dict[str, Any] | None = None) -> Table:
        entity, options = _parse_query(sql)
        types = self._property_types(entity)
        url: str | None = self._url(entity, options)
        records: list[dict[str, Any]] = []
        while url:
            data = self._get(url)
            payload = data.get("d") if isinstance(data, dict) else None
            if isinstance(payload, dict) and isinstance(payload.get("results"), list):
                page, next_url = payload["results"], payload.get("__next")
                url = urljoin(self.base_url + "/odata/v2/", next_url) if next_url else None
            elif isinstance(payload, list):
                page, url = payload, None
            elif isinstance(payload, dict):
                page, url = [payload], None
            else:
                raise ConnectorError("SuccessFactors answered without data")
            records.extend(_flatten(record, types) for record in page)
            if len(records) > self.max_rows:
                raise ConnectorError(
                    f"more than {self.max_rows} rows; narrow the query with $filter or $select"
                )
        selected = next((v for k, v in options if k == "$select"), "")
        order = [s.strip() for s in selected.split(",") if s.strip()]
        columns: list[str] = []
        for record in records:
            for name in record:
                if name not in columns:
                    columns.append(name)

        def position(name: str) -> int:
            for index, wanted in enumerate(order):
                if name == wanted or name.startswith(wanted + "/"):
                    return index
            return len(order)

        columns.sort(key=position)  # stable: keeps SuccessFactors' order within a selection
        if not columns:
            columns = order
        return Table(columns=columns, rows=[tuple(r.get(c) for c in columns) for r in records])

    def close(self) -> None:
        self._token = None
