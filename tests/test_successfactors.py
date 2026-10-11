"""SuccessFactors connector tests against a fake OData API (no tenant needed)."""

import base64
import datetime as dt
import json
import urllib.error
import urllib.request
from decimal import Decimal
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from testbench.connectors import create_connector
from testbench.connectors import successfactors as sf
from testbench.connectors.base import ConnectorError, ObjectRef

pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402

API = "https://api55.sapsf.eu"
BASIC = {
    "api_url": API,
    "company_id": "ACMET1",
    "auth": "basic",
    "username": "api_reader",
    "password": "pw",
}
METADATA = b"""<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx" Version="1.0">
 <edmx:DataServices>
  <Schema xmlns="http://schemas.microsoft.com/ado/2008/09/edm"
          xmlns:sap="http://www.sap.com/Protocols/SAPData" Namespace="SFOData">
   <EntityType Name="EmpJob">
    <Key><PropertyRef Name="userId"/><PropertyRef Name="startDate"/></Key>
    <Property Name="userId" Type="Edm.String" Nullable="false" sap:label="User ID"/>
    <Property Name="startDate" Type="Edm.DateTime" Nullable="false" sap:label="Start Date"/>
    <Property Name="fte" Type="Edm.Decimal" sap:label="FTE"/>
    <Property Name="seqNumber" Type="Edm.Int64"/>
   </EntityType>
  </Schema>
 </edmx:DataServices>
</edmx:Edmx>"""


def record(user: str, day: int, fte: str) -> dict:
    ms = int(dt.datetime(2026, 1, day, tzinfo=dt.timezone.utc).timestamp() * 1000)
    return {
        "__metadata": {"uri": "x", "type": "SFOData.EmpJob"},
        "userId": user,
        "startDate": f"/Date({ms})/",
        "fte": fte,
        "seqNumber": "1",
        "employmentNav": {"__deferred": {"uri": "x"}},
    }


class FakeAPI:
    def __init__(self) -> None:
        self.requests: list[urllib.request.Request] = []
        self.pages: dict[str, dict] = {}
        self.token_status = 200

    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes:
        self.requests.append(request)
        url = urlsplit(request.full_url)
        if url.path == "/oauth/token":
            if self.token_status != 200:
                raise urllib.error.HTTPError(request.full_url, 401, "no", {}, None)
            return json.dumps({"access_token": "tok", "expires_in": 3600}).encode()
        if url.path.endswith("/$metadata"):
            return METADATA
        if url.path == "/odata/v2/":
            return json.dumps({"d": {"EntitySets": ["PerPerson", "EmpJob"]}}).encode()
        if url.path == "/odata/v2/Forbidden":
            body = json.dumps({"error": {"message": {"value": "no read permission"}}})
            raise urllib.error.HTTPError(
                request.full_url, 403, "Forbidden", {}, _Body(body.encode())
            )
        page = parse_qs(url.query).get("page", ["1"])[0]
        return json.dumps(self.pages[page]).encode()


class _Body:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self, *_: object) -> bytes:
        return self.data

    def close(self) -> None:
        pass


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    fake = FakeAPI()
    monkeypatch.setattr(sf, "_send", fake)
    return fake


def test_basic_auth_and_entity_list(api: FakeAPI) -> None:
    connector = create_connector("successfactors", BASIC)
    connector.test_connection()
    header = api.requests[0].get_header("Authorization")
    assert base64.b64decode(header.split()[1]) == b"api_reader@ACMET1:pw"
    assert [o.name for o in connector.list_objects()] == ["EmpJob", "PerPerson"]
    assert "pw" not in repr(connector)


def test_describe_reads_types_keys_and_labels(api: FakeAPI) -> None:
    schema = create_connector("successfactors", BASIC).describe(ObjectRef("EmpJob"))
    columns = {c.name: c for c in schema.columns}
    assert columns["userId"].key and columns["startDate"].key and not columns["fte"].key
    assert columns["fte"].type == "Edm.Decimal" and columns["fte"].label == "FTE"
    assert not columns["userId"].nullable


def test_query_follows_pages_and_converts_values(api: FakeAPI) -> None:
    api.pages["1"] = {
        "d": {
            "results": [record("u1", 1, "1.0")],
            "__next": f"{API}/odata/v2/EmpJob?$skiptoken=x&page=2",
        }
    }
    api.pages["2"] = {"d": {"results": [record("u2", 15, "0.5")]}}
    table = create_connector("successfactors", BASIC).query(
        "EmpJob\n  ?$select=userId,startDate,fte\n  &$filter=company eq 'ACME'\n    and fte gt 0"
    )
    assert table.columns == ["userId", "startDate", "fte", "seqNumber"]
    assert table.rows[1] == ("u2", dt.date(2026, 1, 15), Decimal("0.5"), 1)
    first = urlsplit(api.requests[-2].full_url)
    assert first.path == "/odata/v2/EmpJob"
    assert unquote(first.query).startswith("$select=userId,startDate,fte&$filter=company eq 'ACME'")
    assert "$format=json" in first.query


def test_next_links_to_other_hosts_are_refused(api: FakeAPI) -> None:
    api.pages["1"] = {"d": {"results": [], "__next": "https://evil.example/odata/v2/EmpJob"}}
    with pytest.raises(ConnectorError, match="another host"):
        create_connector("successfactors", BASIC).query("EmpJob")


@pytest.mark.parametrize(
    "query",
    ["../oauth/token", "https://evil.example/x", "EmpJob?$batch=1", "EmpJob?$format=xml", ""],
)
def test_only_entity_reads_are_allowed(query: str) -> None:
    with pytest.raises(ConnectorError):
        sf._parse_query(query)


def test_permission_errors_are_readable(api: FakeAPI) -> None:
    with pytest.raises(ConnectorError, match="no read permission"):
        create_connector("successfactors", BASIC).query("Forbidden")


def _key_pem() -> tuple[rsa.RSAPrivateKey, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return key, pem


def test_oauth_signs_a_saml_assertion_and_uses_the_token(api: FakeAPI) -> None:
    key, pem = _key_pem()
    settings = {
        **BASIC,
        "auth": "oauth",
        "client_id": "CLIENT",
        "user_id": "u1",
        "private_key": pem,
    }
    connector = create_connector("successfactors", settings)
    connector.test_connection()
    connector.test_connection()

    token_requests = [r for r in api.requests if r.full_url.endswith("/oauth/token")]
    assert len(token_requests) == 1  # the token is reused
    form = parse_qs(token_requests[0].data.decode())
    assert form["company_id"] == ["ACMET1"] and form["client_id"] == ["CLIENT"]
    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:saml2-bearer"]
    assertion = base64.b64decode(form["assertion"][0]).decode()
    assert "<saml2:NameID" in assertion and ">u1</saml2:NameID>" in assertion
    assert f'Recipient="{API}/oauth/token"' in assertion
    assert pem.splitlines()[1] not in assertion  # the key itself is never sent

    # The signature covers the canonical SignedInfo, the digest covers the assertion.
    signed_info = assertion[
        assertion.index("<ds:SignedInfo>") : assertion.index("</ds:SignedInfo>")
    ]
    canonical = (
        signed_info.replace(
            "<ds:SignedInfo>", '<ds:SignedInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
        )
        + "</ds:SignedInfo>"
    )
    value = assertion.split("<ds:SignatureValue>")[1].split("</ds:SignatureValue>")[0]
    key.public_key().verify(
        base64.b64decode(value), canonical.encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    assert all(r.get_header("Authorization") == "Bearer tok" for r in api.requests[1:])


def test_oauth_refusal_explains_what_to_check(api: FakeAPI) -> None:
    api.token_status = 401
    _, pem = _key_pem()
    settings = {**BASIC, "auth": "oauth", "client_id": "C", "user_id": "u", "private_key": pem}
    with pytest.raises(ConnectorError, match="private key matches"):
        create_connector("successfactors", settings).test_connection()


def test_form_settings_keep_only_what_the_method_needs() -> None:
    _, pem = _key_pem()
    form = {
        "api_url": "api55.sapsf.eu/login",
        "company_id": " ACMET1 ",
        "auth": "oauth",
        "client_id": " C ",
        "user_id": "u1",
        "private_key": pem,
        "username": "leftover",
        "password": "leftover",
    }
    settings = sf.SuccessFactorsConnector.check_settings(form)
    assert settings["api_url"] == API and settings["company_id"] == "ACMET1"
    assert "password" not in settings and settings["client_id"] == "C"
    basic = sf.SuccessFactorsConnector.check_settings({**form, "auth": "basic"})
    assert "private_key" not in basic and basic["username"] == "leftover"


@pytest.mark.parametrize(
    "change",
    [
        {"api_url": "https://internal.example"},
        {"api_url": "http://api55.sapsf.eu"},
        {"company_id": ""},
        {"private_key": "not a key"},
        {"user_id": ""},
        {"auth": "magic"},
    ],
)
def test_form_settings_are_rejected(change: dict) -> None:
    _, pem = _key_pem()
    form = {
        "api_url": API,
        "company_id": "ACMET1",
        "auth": "oauth",
        "client_id": "C",
        "user_id": "u1",
        "private_key": pem,
    }
    with pytest.raises(ConnectorError):
        sf.SuccessFactorsConnector.check_settings({**form, **change})


def test_redirects_are_never_followed() -> None:
    handler = sf._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example") is None
