import json
import socket
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from core.api_operation_store import ApiOperationStore
from core.agent_capability_mapper import build_agent_capability_map, map_future_steps_to_capabilities
from core.openapi_importer import (
    InvalidSpecError,
    UnsupportedVersionError,
    _discover_spec_url_from_html,
    parse_openapi_document,
)
from core.url_safety import UnsafeUrlError, assert_safe_target_url


def sample_spec():
    return {
        "openapi": "3.0.3",
        "info": {"title": "EP PoBox API V1", "version": "1"},
        "servers": [{"url": "https://api.example.com/services/pobox?token=SHOULD_NOT_STORE"}],
        "security": [{"BearerAuth": []}],
        "paths": {
            "/api/v1/Account/passwordLessToken": {
                "post": {
                    "operationId": "passwordLessToken",
                    "summary": "Create passwordless customer login token",
                    "tags": ["Account"],
                    "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"email": {"type": "string", "example": "secret@example.com"}}}}}},
                    "responses": {"200": {"description": "OK", "example": {"token": "SECRET"}}},
                }
            },
            "/api/v1/Account/verifyPasswordLessToken": {
                "post": {
                    "operationId": "verifyPasswordLessToken",
                    "summary": "Verify passwordless token for customer account",
                    "tags": ["Account"],
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/v1/boxes": {
                "get": {
                    "operationId": "getAvailableBoxes",
                    "summary": "Get available PO boxes",
                    "tags": ["PoBox"],
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    }


def test_parse_openapi_operations():
    metadata, ops = parse_openapi_document(sample_spec(), "https://docs.example.com/swagger.json")
    assert metadata["title"] == "EP PoBox API V1"
    assert metadata["openapi_version"] == "3.0.3"
    assert len(ops) == 3
    assert {op["method"] for op in ops} == {"GET", "POST"}


def test_operation_id_method_path_preserved():
    _, ops = parse_openapi_document(sample_spec(), "https://docs.example.com/swagger.json")
    op = next(item for item in ops if item["operation_id"] == "verifyPasswordLessToken")
    assert op["method"] == "POST"
    assert op["path"] == "/api/v1/Account/verifyPasswordLessToken"


def test_security_names_only():
    _, ops = parse_openapi_document(sample_spec(), "https://docs.example.com/swagger.json")
    assert ops[0]["security_requirements"] == ["BearerAuth"]
    dump = json.dumps(ops)
    assert "SHOULD_NOT_STORE" not in dump


def test_examples_and_token_values_stripped_from_schemas():
    _, ops = parse_openapi_document(sample_spec(), "https://docs.example.com/swagger.json")
    dump = json.dumps(ops)
    assert "secret@example.com" not in dump
    assert '"SECRET"' not in dump


def test_server_query_removed():
    metadata, _ = parse_openapi_document(sample_spec(), "https://docs.example.com/swagger.json")
    assert metadata["servers"] == ["https://api.example.com/services/pobox"]


def test_no_paths_rejected():
    with pytest.raises(InvalidSpecError):
        parse_openapi_document({"openapi": "3.0.0", "info": {}, "paths": {}}, "https://x.example/a")


def test_unsupported_version_rejected():
    with pytest.raises(UnsupportedVersionError):
        parse_openapi_document({"openapi": "4.0.0", "paths": {"/x": {"get": {}}}}, "https://x.example/a")


def test_swagger2_supported():
    doc = {"swagger": "2.0", "info": {"title": "Legacy", "version": "1"}, "host": "api.example.com", "basePath": "/v1", "paths": {"/x": {"get": {"operationId": "getX", "responses": {"200": {"description": "ok"}}}}}}
    metadata, ops = parse_openapi_document(doc, "https://docs.example.com/swagger.json")
    assert metadata["format"] == "SWAGGER"
    assert metadata["servers"] == ["https://api.example.com/v1"]
    assert ops[0]["operation_id"] == "getX"


def test_swagger_ui_relative_spec_discovery():
    html = '<script>SwaggerUIBundle({ url: "/services/pobox/swagger/v1/swagger.json" })</script>'
    assert _discover_spec_url_from_html(html, "https://box.example.com/services/pobox/index.html") == "https://box.example.com/services/pobox/swagger/v1/swagger.json"


def test_swagger_ui_missing_spec_safe_error():
    with pytest.raises(InvalidSpecError):
        _discover_spec_url_from_html("<html>No swagger config</html>", "https://box.example.com/index.html")


def test_swagger_ui_ambiguous_spec_safe_error():
    html = '<script>const a={url:"/a.json"}; const b={url:"/b.json"};</script>'
    with pytest.raises(InvalidSpecError):
        _discover_spec_url_from_html(html, "https://box.example.com/index.html")


def _public_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def _private_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))]


def test_safe_https_url_allowed(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    assert assert_safe_target_url("https://api.example.com/swagger.json")


def test_http_rejected_by_default(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    monkeypatch.delenv("ZX_OPENAPI_ALLOW_HTTP", raising=False)
    with pytest.raises(UnsafeUrlError):
        assert_safe_target_url("http://api.example.com/swagger.json")


def test_localhost_rejected():
    with pytest.raises(UnsafeUrlError):
        assert_safe_target_url("https://localhost/swagger.json")


def test_loopback_rejected():
    with pytest.raises(UnsafeUrlError):
        assert_safe_target_url("https://127.0.0.1/swagger.json")


def test_private_dns_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _private_dns)
    with pytest.raises(UnsafeUrlError):
        assert_safe_target_url("https://internal.example.com/swagger.json")


def test_credentials_in_url_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    with pytest.raises(UnsafeUrlError):
        assert_safe_target_url("https://user:pass@api.example.com/swagger.json")
    with pytest.raises(UnsafeUrlError):
        assert_safe_target_url("https://api.example.com/swagger.json?token=abc")


def test_operation_store_round_trip_and_refresh_preserves_source_id():
    with TemporaryDirectory() as td:
        store = ApiOperationStore(Path(td) / "db.sqlite")
        metadata, ops = parse_openapi_document(sample_spec(), "https://docs.example.com/swagger.json")
        first = store.upsert_source_and_operations("t1", "s1", "i1", metadata, ops, "SANDBOX")
        first_id = first["id"]
        assert len(store.list_operations_for_integration("t1", "i1", "s1")) == 3
        metadata["api_version"] = "2"
        second = store.upsert_source_and_operations("t1", "s1", "i1", metadata, ops[:1], "SANDBOX")
        assert second["id"] == first_id
        assert second["api_version"] == "2"
        assert len(store.list_operations_for_integration("t1", "i1", "s1")) == 1


def test_operation_store_tenant_scope():
    with TemporaryDirectory() as td:
        store = ApiOperationStore(Path(td) / "db.sqlite")
        metadata, ops = parse_openapi_document(sample_spec(), "https://docs.example.com/swagger.json")
        store.upsert_source_and_operations("t1", "s1", "i1", metadata, ops, "SANDBOX")
        assert store.list_operations_for_integration("t2", "i1") == []


def _caps(status="CONNECTED"):
    return [{"id": "i1", "name": "EP PoBox API", "capability_type": "GOVERNMENT_API", "status": status, "available": status == "CONNECTED", "sandbox": status == "SANDBOX"}]


def _op(operation_id, path, summary, environment="CONNECTED"):
    return {"integration_id": "i1", "operation_id": operation_id, "method": "POST", "path": path, "summary": summary, "tags": ["Account"], "description": "", "environment": environment, "enabled": True}


def test_structured_operation_preferred_and_traceable():
    steps = [{"step_number": 1, "name": "Verify passwordless token", "type": "SYSTEM"}]
    ops = [_op("verifyPasswordLessToken", "/api/v1/Account/verifyPasswordLessToken", "Verify passwordless token for account")]
    result = map_future_steps_to_capabilities(steps, _caps(), ops)
    assert result[0]["capability_status"] == "AUTOMATE"
    assert result[0]["mapped_integration"]["operation"]["operation_id"] == "verifyPasswordLessToken"
    assert "OpenAPI operation" in result[0]["reason"]


def test_structured_not_connected_is_integration_required():
    steps = [{"name": "Verify passwordless token", "type": "SYSTEM"}]
    ops = [_op("verifyPasswordLessToken", "/verifyPasswordLessToken", "Verify passwordless token")]
    result = map_future_steps_to_capabilities(steps, _caps("NOT_CONNECTED"), ops)
    assert result[0]["capability_status"] == "INTEGRATION_REQUIRED"
    assert result[0]["mapped_integration"] is None


def test_structured_sandbox_preserved():
    steps = [{"name": "Verify passwordless token", "type": "SYSTEM"}]
    ops = [_op("verifyPasswordLessToken", "/verifyPasswordLessToken", "Verify passwordless token", "SANDBOX")]
    result = map_future_steps_to_capabilities(steps, _caps("SANDBOX"), ops)
    assert result[0]["capability_status"] == "AUTOMATE"
    assert result[0]["mapped_integration"]["sandbox"] is True


def test_weak_keyword_overlap_does_not_bind_structured_operation():
    steps = [{"name": "Check customer account", "type": "SYSTEM"}]
    ops = [_op("deleteAccount", "/account", "Delete account")]
    # Structured operation should not be selected on the single weak 'account' token.
    result = map_future_steps_to_capabilities(steps, [], ops)
    assert result[0]["capability_status"] == "INTEGRATION_REQUIRED"


def test_ambiguous_structured_match_does_not_choose_arbitrarily():
    steps = [{"name": "Verify passwordless token", "type": "SYSTEM"}]
    ops = [
        _op("verifyPasswordlessTokenA", "/a/verify/passwordless/token", "Verify passwordless token"),
        _op("verifyPasswordlessTokenB", "/b/verify/passwordless/token", "Verify passwordless token"),
    ]
    result = map_future_steps_to_capabilities(steps, [], ops)
    assert result[0]["capability_status"] == "INTEGRATION_REQUIRED"


def test_legacy_manual_integration_fallback_still_works():
    steps = [{"name": "Use EP PoBox API for renewal", "type": "SYSTEM"}]
    result = map_future_steps_to_capabilities(steps, _caps(), [])
    assert result[0]["capability_status"] == "AUTOMATE"
    assert "operation" not in result[0]["mapped_integration"]


def test_capability_map_contains_no_operation_credentials():
    steps = [{"name": "Verify passwordless token", "type": "SYSTEM"}]
    ops = [_op("verifyPasswordLessToken", "/verifyPasswordLessToken", "Verify passwordless token")]
    result = build_agent_capability_map("s1", [], [{"id":"i1","name":"EP PoBox API","type":"GOVERNMENT_API","status":"CONNECTED","secret_reference":"vault/secret","config":{"api_key":"x"}}], steps, ops)
    dump = json.dumps(result).lower()
    assert "secret_reference" not in dump
    assert "api_key" not in dump
    assert "vault/secret" not in dump


def _ep_op(operation_id, method, path, tag):
    return {
        "integration_id": "i1", "operation_id": operation_id, "method": method,
        "path": path, "summary": "", "tags": [tag], "description": "",
        "environment": "CONNECTED", "enabled": True,
    }


def test_rent_pobox_identity_maps_to_verify_passwordless_token():
    steps = [{"name": "Confirm identity and service context", "type": "SYSTEM"}]
    ops = [
        _ep_op("passwordLessToken", "POST", "/api/v1/Account/passwordLessToken", "Account"),
        _ep_op("verifyPasswordLessToken", "POST", "/api/v1/Account/verifyPasswordLessToken", "Account"),
    ]
    result = map_future_steps_to_capabilities(steps, _caps(), ops, service_context="Rent Personal P.O. Box")
    assert result[0]["capability_status"] == "AUTOMATE"
    assert result[0]["mapped_integration"]["operation"]["operation_id"] == "verifyPasswordLessToken"


def test_rent_pobox_select_plan_maps_to_rental_select():
    steps = [{"name": "Select subscription plan", "type": "SYSTEM"}]
    ops = [
        _ep_op("Bundle", "GET", "/api/v1/Rental/Bundle", "Rental"),
        _ep_op("Select", "POST", "/api/v1/Rental/Select", "Rental"),
        _ep_op("GetAdditionalOptions", "GET", "/api/v1/Renewal/GetAdditionalOptions", "Renewal"),
    ]
    result = map_future_steps_to_capabilities(steps, _caps(), ops, service_context="Rent Personal P.O. Box")
    assert result[0]["capability_status"] == "AUTOMATE"
    assert result[0]["mapped_integration"]["operation"]["path"] == "/api/v1/Rental/Select"


def test_rent_pobox_payment_prefers_rental_operation_over_renewal_payment():
    steps = [{"name": "Process payment", "type": "SYSTEM"}]
    ops = [
        _ep_op("ProcessPayment", "POST", "/api/v1/Renewal/ProcessPayment", "Renewal"),
        _ep_op("UpdatePayment", "POST", "/api/v1/Rental/UpdatePayment/{paymentReferenceNo}", "Rental"),
        _ep_op("ConfirmPayment", "POST", "/api/v1/Guest/Renewal/ConfirmPayment", "Guest"),
    ]
    result = map_future_steps_to_capabilities(steps, _caps(), ops, service_context="Rent Personal P.O. Box")
    assert result[0]["capability_status"] == "AUTOMATE"
    assert result[0]["mapped_integration"]["operation"]["path"] == "/api/v1/Rental/UpdatePayment/{paymentReferenceNo}"


def test_rent_pobox_arabic_payment_prefers_rental_operation():
    steps = [{"name": "دفع الرسوم", "action": "إتمام الدفع", "type": "SYSTEM"}]
    ops = [
        _ep_op("ProcessPayment", "POST", "/api/v1/Renewal/ProcessPayment", "Renewal"),
        _ep_op("UpdatePayment", "POST", "/api/v1/Rental/UpdatePayment/{paymentReferenceNo}", "Rental"),
    ]
    result = map_future_steps_to_capabilities(steps, _caps(), ops, service_context="Rent Personal P.O. Box")
    assert result[0]["capability_status"] == "AUTOMATE"
    assert result[0]["mapped_integration"]["operation"]["path"].startswith("/api/v1/Rental/")


def test_unrelated_step_still_does_not_invent_endpoint():
    steps = [{"name": "Handle objections", "type": "SYSTEM"}]
    ops = [
        _ep_op("Select", "POST", "/api/v1/Rental/Select", "Rental"),
        _ep_op("UpdatePayment", "POST", "/api/v1/Rental/UpdatePayment/{paymentReferenceNo}", "Rental"),
    ]
    result = map_future_steps_to_capabilities(steps, _caps(), ops, service_context="Rent Personal P.O. Box")
    assert result[0]["capability_status"] == "INTEGRATION_REQUIRED"
    assert result[0]["mapped_integration"] is None
