"""Safe discovery-only OpenAPI/Swagger importer.

This module fetches a specification document or a Swagger UI page and returns
sanitized metadata/operation descriptions. It never executes API operations.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from core.url_safety import UnsafeUrlError, assert_safe_target_url

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

MAX_SPEC_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


class OpenApiImportError(ValueError):
    code = "OPENAPI_IMPORT_FAILED"


class UnreachableSpecError(OpenApiImportError):
    code = "OPENAPI_UNREACHABLE"


class InvalidSpecError(OpenApiImportError):
    code = "OPENAPI_INVALID"


class UnsupportedVersionError(OpenApiImportError):
    code = "OPENAPI_UNSUPPORTED_VERSION"


class SpecTooLargeError(OpenApiImportError):
    code = "OPENAPI_SPEC_TOO_LARGE"


def _safe_get(url: str, timeout: float = 8.0):
    current = assert_safe_target_url(url)
    session = requests.Session()
    for _ in range(MAX_REDIRECTS + 1):
        try:
            response = session.get(current, timeout=timeout, allow_redirects=False, stream=True,
                                   headers={"Accept": "application/json, application/yaml, text/yaml, text/html;q=0.8, */*;q=0.2"})
        except requests.RequestException as exc:
            raise UnreachableSpecError("OpenAPI/Swagger URL could not be reached.") from exc
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            if not location:
                raise UnreachableSpecError("OpenAPI redirect target is missing.")
            current = assert_safe_target_url(urljoin(current, location))
            continue
        if response.status_code >= 400:
            raise UnreachableSpecError("OpenAPI/Swagger URL returned an unsuccessful response.")
        chunks, total = [], 0
        try:
            for chunk in response.iter_content(65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_SPEC_BYTES:
                    raise SpecTooLargeError("OpenAPI specification exceeds the allowed size limit.")
                chunks.append(chunk)
        finally:
            response.close()
        return current, b"".join(chunks), response.headers.get("Content-Type", "")
    raise UnreachableSpecError("OpenAPI URL redirected too many times.")


def _parse_document(raw: bytes):
    text = raw.decode("utf-8-sig", errors="strict")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        if yaml is None:
            raise InvalidSpecError("Specification is not valid JSON and YAML support is unavailable.")
        try:
            doc = yaml.safe_load(text)
        except Exception as exc:
            raise InvalidSpecError("Specification is not valid JSON or YAML.") from exc
    if not isinstance(doc, dict):
        raise InvalidSpecError("OpenAPI specification root must be an object.")
    return doc


def _looks_like_spec(doc):
    return isinstance(doc, dict) and ("openapi" in doc or "swagger" in doc)


def _discover_spec_url_from_html(html: str, page_url: str):
    # Common SwaggerUIBundle forms: url: "..." or urls: [{url:"..."}]
    patterns = [
        r"\burl\s*:\s*['\"]([^'\"]+)['\"]",
        r"['\"]url['\"]\s*:\s*['\"]([^'\"]+)['\"]",
        r"(?:href|src)=['\"]([^'\"]*(?:swagger|openapi)[^'\"]*\.(?:json|ya?ml)(?:\?[^'\"]*)?)['\"]",
    ]
    candidates = []
    for pattern in patterns:
        candidates.extend(re.findall(pattern, html, flags=re.I))
    # Deterministic, deduplicated. Ambiguous UI configs are rejected rather
    # than arbitrarily selecting one definition.
    resolved = []
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in {"/", "#"}:
            absolute = urljoin(page_url, candidate)
            if absolute not in resolved:
                resolved.append(absolute)
    if len(resolved) == 1:
        return resolved[0]
    if not resolved:
        raise InvalidSpecError("Swagger UI page does not expose a discoverable OpenAPI JSON/YAML URL. Please provide the direct specification URL.")
    raise InvalidSpecError("Swagger UI exposes multiple API definitions. Please provide the direct OpenAPI JSON/YAML URL for the intended definition.")


_SCHEMA_VALUE_KEYS_TO_STRIP = {"example", "examples", "default", "authorization", "token", "api_key", "apikey", "password", "secret"}

def _strip_schema_values(value, depth=0):
    if depth > 20:
        return {"truncated": True}
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if str(key).strip().lower() in _SCHEMA_VALUE_KEYS_TO_STRIP:
                continue
            cleaned[str(key)] = _strip_schema_values(item, depth + 1)
        return cleaned
    if isinstance(value, list):
        return [_strip_schema_values(item, depth + 1) for item in value[:500]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(type(value).__name__)



def _safe_text(value, limit):
    text = str(value or "")[:limit]
    # Best-effort removal of credential-like literals from descriptive text.
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]{8,}", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:api[_ -]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", text)
    return text


def _safe_schema(value, max_chars=50_000):
    if value is None:
        return None
    cleaned = _strip_schema_values(value)
    try:
        serialized = json.dumps(cleaned, ensure_ascii=False)
    except TypeError:
        return None
    if len(serialized) > max_chars:
        return {"truncated": True}
    return cleaned




def _sanitize_server_url(value):
    text = str(value or "").strip()
    if not text:
        return None
    # Relative/template server URLs are metadata only; retain them as text.
    if "://" not in text:
        return text[:2000]
    try:
        parsed = urlsplit(text)
    except ValueError:
        return None
    if parsed.username or parsed.password:
        return None
    # Query strings/fragments are not required to identify an API server and
    # can accidentally carry secret material.
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))[:2000]


def _security_names(value):
    names = []
    for requirement in value or []:
        if isinstance(requirement, dict):
            for key in requirement.keys():
                key = str(key)
                if key not in names:
                    names.append(key)
    return names


def parse_openapi_document(doc, source_url: str):
    openapi_version = str(doc.get("openapi") or "").strip()
    swagger_version = str(doc.get("swagger") or "").strip()
    if openapi_version:
        if not openapi_version.startswith("3."):
            raise UnsupportedVersionError(f"Unsupported OpenAPI version: {openapi_version}")
        api_format = "OPENAPI"
        version = openapi_version
    elif swagger_version:
        if swagger_version != "2.0":
            raise UnsupportedVersionError(f"Unsupported Swagger version: {swagger_version}")
        api_format = "SWAGGER"
        version = swagger_version
    else:
        raise InvalidSpecError("Document is not an OpenAPI/Swagger specification.")

    paths = doc.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise InvalidSpecError("OpenAPI specification contains no paths.")

    info = doc.get("info") if isinstance(doc.get("info"), dict) else {}
    servers = []
    if api_format == "OPENAPI":
        for server in doc.get("servers") or []:
            if isinstance(server, dict) and server.get("url"):
                safe_server = _sanitize_server_url(server["url"])
                if safe_server:
                    servers.append(safe_server)
    else:
        scheme = ((doc.get("schemes") or ["https"])[0] if isinstance(doc.get("schemes"), list) else "https")
        host = str(doc.get("host") or "").strip()
        base_path = str(doc.get("basePath") or "").strip()
        if host:
            safe_server = _sanitize_server_url(f"{scheme}://{host}{base_path}")
            if safe_server:
                servers.append(safe_server)

    global_security = doc.get("security") or []
    operations = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        path_parameters = path_item.get("parameters") if isinstance(path_item.get("parameters"), list) else []
        for method, operation in path_item.items():
            if str(method).lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            op_security = operation.get("security", global_security)
            parameters = list(path_parameters) + (operation.get("parameters") if isinstance(operation.get("parameters"), list) else [])
            request_schema = None
            if api_format == "OPENAPI":
                request_schema = operation.get("requestBody")
            else:
                body_params = [p for p in parameters if isinstance(p, dict) and p.get("in") == "body"]
                request_schema = body_params[0].get("schema") if body_params else None
            responses = operation.get("responses") if isinstance(operation.get("responses"), dict) else {}
            operations.append({
                "operation_id": str(operation.get("operationId") or "").strip() or None,
                "method": str(method).upper(),
                "path": str(path),
                "summary": _safe_text(operation.get("summary"), 1000),
                "description": _safe_text(operation.get("description"), 5000),
                "tags": [str(t)[:200] for t in (operation.get("tags") or []) if isinstance(t, (str, int, float))],
                "parameters": _safe_schema(parameters),
                "request_schema": _safe_schema(request_schema),
                "response_schema": _safe_schema(responses),
                "security_requirements": _security_names(op_security),
                "source": "OPENAPI",
                "enabled": True,
            })
    if not operations:
        raise InvalidSpecError("OpenAPI specification contains no supported operations.")
    return {
        "source_url": source_url,
        "title": _safe_text(info.get("title") or "Imported OpenAPI", 500),
        "api_version": str(info.get("version") or "")[:100],
        "openapi_version": version,
        "format": api_format,
        "servers": servers[:20],
    }, operations


def fetch_and_parse(url: str):
    final_url, raw, content_type = _safe_get(url)
    is_html = "text/html" in content_type.lower() or raw.lstrip().lower().startswith((b"<!doctype html", b"<html"))
    if is_html:
        html = raw.decode("utf-8", errors="replace")
        spec_url = _discover_spec_url_from_html(html, final_url)
        # The discovered target is validated independently in _safe_get.
        final_url, raw, _ = _safe_get(spec_url)
    try:
        doc = _parse_document(raw)
    except UnicodeDecodeError as exc:
        raise InvalidSpecError("OpenAPI specification is not valid UTF-8 text.") from exc
    if not _looks_like_spec(doc):
        raise InvalidSpecError("Fetched document is not an OpenAPI/Swagger specification.")
    return parse_openapi_document(doc, final_url)
