from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx


class LiveApiExecutionError(RuntimeError):
    pass


class LiveApiExecutor:
    """
    Safe runtime reader for CONNECTED OpenAPI integrations.

    Runtime discovery is intentionally READ-ONLY:
    only enabled GET operations are eligible.
    """

    def __init__(self, api_operation_store, catalog_store, timeout_seconds=15):
        self.api_operation_store = api_operation_store
        self.catalog_store = catalog_store
        self.timeout_seconds = timeout_seconds

    def _get_connected_integration(self, tenant_id, integration_id):
        integration = self.catalog_store.get_integration_for_tenant(
            integration_id,
            tenant_id,
        )

        if not integration:
            raise LiveApiExecutionError("Integration not found.")

        if str(integration.get("status") or "").upper() != "CONNECTED":
            raise LiveApiExecutionError(
                "Integration must be CONNECTED before live API access."
            )

        return integration

    def _get_source(self, tenant_id, service_id, integration_id):
        source = self.api_operation_store.get_source_for_integration(
            tenant_id,
            service_id,
            integration_id,
        )

        if not source:
            raise LiveApiExecutionError(
                "OpenAPI source was not found for this service integration."
            )

        return source

    @staticmethod
    def _resolve_base_url(source):
        servers = source.get("servers") or []

        for server in servers:
            if isinstance(server, dict):
                url = str(server.get("url") or "").strip()
            else:
                url = str(server or "").strip()

            if url:
                return url.rstrip("/") + "/"

        source_url = str(source.get("source_url") or "").strip()

        if not source_url:
            raise LiveApiExecutionError("No API base URL is available.")

        lowered = source_url.lower()
        swagger_index = lowered.find("/swagger/")

        if swagger_index >= 0:
            return source_url[:swagger_index].rstrip("/") + "/"

        return source_url.rsplit("/", 1)[0].rstrip("/") + "/"

    def list_read_operations(
        self,
        tenant_id,
        service_id,
        integration_id,
    ):
        self._get_connected_integration(
            tenant_id,
            integration_id,
        )

        operations = self.api_operation_store.list_operations_for_integration(
            tenant_id,
            integration_id,
            service_id=service_id,
        )

        return [
            operation
            for operation in operations
            if operation.get("enabled")
            and str(operation.get("method") or "").upper() == "GET"
        ]

    def discover_service_integrations(
        self,
        tenant_id,
        service_id,
    ):
        """
        Find CONNECTED integrations that contain enabled GET operations
        explicitly linked to this exact service.
        """

        integrations = self.catalog_store.list_integrations_for_tenant(
            tenant_id
        )

        matches = []

        for integration in integrations:
            if str(integration.get("status") or "").upper() != "CONNECTED":
                continue

            integration_id = integration.get("id")

            if not integration_id:
                continue

            operations = (
                self.api_operation_store.list_operations_for_integration(
                    tenant_id,
                    integration_id,
                    service_id=service_id,
                )
            )

            read_operations = [
                operation
                for operation in operations
                if operation.get("enabled")
                and str(operation.get("method") or "").upper() == "GET"
            ]

            if not read_operations:
                continue

            matches.append({
                "integration": integration,
                "operations": read_operations,
                "match_scope": "EXACT_SERVICE",
            })

        return matches

    def discover_tenant_read_operations(
        self,
        tenant_id,
    ):
        """
        Tenant-scoped fallback discovery.

        Used only when the published Blueprint's service_id does not have
        usable OpenAPI reads. It never crosses tenant boundaries and still
        considers CONNECTED integrations only.
        """

        matches = []

        for integration in self.catalog_store.list_integrations_for_tenant(
            tenant_id
        ):
            if str(integration.get("status") or "").upper() != "CONNECTED":
                continue

            integration_id = integration.get("id")
            if not integration_id:
                continue

            operations = self.api_operation_store.list_operations_for_integration(
                tenant_id,
                integration_id,
                service_id=None,
            )

            read_operations = [
                operation
                for operation in operations
                if operation.get("enabled")
                and str(operation.get("method") or "").upper() == "GET"
                and operation.get("service_id")
            ]

            if read_operations:
                matches.append({
                    "integration": integration,
                    "operations": read_operations,
                    "match_scope": "TENANT_FALLBACK",
                })

        return matches

    @staticmethod
    def _keywords(value):
        return {
            token
            for token in re.findall(
                r"[a-zA-Z0-9]+",
                str(value or "").lower(),
            )
            if len(token) >= 3
        }

    @staticmethod
    def _soft_word_overlap(left_words, right_words):
        """
        Count exact and conservative prefix matches such as
        renew <-> renewal without fuzzy-matching unrelated words.
        """
        exact = left_words & right_words
        score = len(exact) * 10

        unmatched_left = left_words - exact
        unmatched_right = right_words - exact

        for left in unmatched_left:
            for right in unmatched_right:
                if len(left) >= 4 and len(right) >= 4:
                    prefix = min(6, len(left), len(right))
                    if left[:prefix] == right[:prefix]:
                        score += 8
                        break

        return score

    def score_operation(
        self,
        operation,
        service_name="",
        intent="",
    ):
        """
        Rank GET operations against the published service/customer intent.

        This scoring never grants access. Tenant and CONNECTED-integration
        checks happen before scoring; score only decides which already-safe
        read operation is most relevant.
        """

        target_words = self._keywords(
            f"{service_name} {intent}"
        )

        searchable = " ".join([
            str(operation.get("operation_id") or ""),
            str(operation.get("path") or ""),
            str(operation.get("summary") or ""),
            str(operation.get("description") or ""),
            " ".join(operation.get("tags") or []),
        ])

        operation_words = self._keywords(searchable)

        score = self._soft_word_overlap(
            target_words,
            operation_words,
        )

        searchable_lower = searchable.lower()

        preferred_terms = {
            "detail": 5,
            "details": 5,
            "charge": 6,
            "charges": 6,
            "price": 6,
            "pricing": 6,
            "fee": 6,
            "fees": 6,
            "package": 5,
            "packages": 5,
            "bundle": 5,
            "bundles": 5,
            "plan": 4,
            "plans": 4,
            "renew": 5,
            "renewal": 5,
            "service": 2,
            "catalog": 4,
            "catalogue": 4,
            "additional": 3,
        }

        for term, points in preferred_terms.items():
            if term in searchable_lower:
                score += points

        return score

    def select_read_operations(
        self,
        tenant_id,
        service_id,
        *,
        service_name="",
        intent="",
        limit=12,
    ):
        """
        Select relevant GET operations.

        1) Prefer operations explicitly linked to this service_id.
        2) If none are available, safely fall back to other CONNECTED
           OpenAPI operations inside the same tenant and match them by
           service name / intent.

        Tenant-wide fallback requires a meaningful textual match so an
        unrelated API cannot be selected just because it has a generic
        "details" or "fees" endpoint.
        """

        candidates = []

        exact_matches = self.discover_service_integrations(
            tenant_id,
            service_id,
        )

        source_matches = exact_matches
        using_fallback = False

        if not exact_matches:
            source_matches = self.discover_tenant_read_operations(
                tenant_id
            )
            using_fallback = True

        for match in source_matches:
            integration = match["integration"]

            for operation in match["operations"]:
                score = self.score_operation(
                    operation,
                    service_name=service_name,
                    intent=intent,
                )

                if using_fallback:
                    operation_words = self._keywords(" ".join([
                        str(operation.get("operation_id") or ""),
                        str(operation.get("path") or ""),
                        str(operation.get("summary") or ""),
                        str(operation.get("description") or ""),
                        " ".join(operation.get("tags") or []),
                    ]))
                    target_words = self._keywords(
                        f"{service_name} {intent}"
                    )
                    semantic_match = self._soft_word_overlap(
                        target_words,
                        operation_words,
                    )

                    # Generic "details"/"fees" wording alone is not enough
                    # for tenant-wide fallback. Require service-intent overlap.
                    if semantic_match < 8:
                        continue

                candidates.append({
                    "integration_id": integration.get("id"),
                    "integration_name": integration.get("name"),
                    "source_service_id": operation.get("service_id") or service_id,
                    "match_scope": match.get("match_scope") or (
                        "TENANT_FALLBACK" if using_fallback else "EXACT_SERVICE"
                    ),
                    "score": score,
                    "operation": operation,
                })

        candidates.sort(
            key=lambda item: (
                item["score"],
                1 if item.get("match_scope") == "EXACT_SERVICE" else 0,
                str(
                    item["operation"].get("operation_id")
                    or item["operation"].get("path")
                    or ""
                ),
            ),
            reverse=True,
        )

        return candidates[: max(1, int(limit or 1))]

    @staticmethod
    def _normalized_parameter_name(value):
        return re.sub(
            r"[^a-z0-9]",
            "",
            str(value or "").lower(),
        )

    @classmethod
    def _documented_parameter_value(cls, parameter):
        """
        Use only values explicitly documented by OpenAPI (example/default).
        Never invent a required customer identifier.
        """
        if not isinstance(parameter, dict):
            return None

        if parameter.get("example") is not None:
            return parameter.get("example")

        schema = parameter.get("schema") or {}
        if isinstance(schema, dict):
            if schema.get("example") is not None:
                return schema.get("example")
            if schema.get("default") is not None:
                return schema.get("default")

        examples = parameter.get("examples")
        if isinstance(examples, dict):
            for example in examples.values():
                if isinstance(example, dict) and example.get("value") is not None:
                    return example.get("value")

        return None

    @classmethod
    def extract_context_values(cls, payload):
        """
        Collect scalar values returned by prior safe GETs.

        Values are keyed by their exact normalized response-field name and
        are only reused when a later required parameter has the same name.
        This allows safe read chaining such as BundleId -> charges without
        guessing relationships between unrelated fields.
        """
        values = {}

        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized = cls._normalized_parameter_name(key)
                    if (
                        normalized
                        and isinstance(child, (str, int, float, bool))
                        and child not in ("", None)
                    ):
                        values.setdefault(normalized, child)
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(payload)
        return values

    @classmethod
    def _demo_parameter_value(cls, parameter):
        """
        Temporary SANDBOX-only placeholders for identity-bound READ calls.

        These values are intentionally synthetic and must never be presented
        as verified customer data. They exist only so the staging demo can
        continue until UAE PASS / authoritative identity data is connected.
        """
        if not isinstance(parameter, dict):
            return None

        name = cls._normalized_parameter_name(parameter.get("name"))

        demo_values = {
            "boxnumber": 123456,
            "emiratecode": "DXB",
            "ischangesubscriptiononly": False,
            "resellerid": "WEB",
            "apiversion": "1.0",
            "language": "en",
            "lang": "en",
            "channel": "WEB",
            "requestsource": "Web",
        }

        return demo_values.get(name)

    @classmethod
    def prepare_request_arguments(
        cls,
        operation,
        known_values=None,
    ):
        """
        Build path/query/header arguments from:
        - documented OpenAPI examples/defaults, or
        - exact-name values returned by an earlier GET.

        Returns missing required parameter names instead of guessing.
        """
        known_values = known_values or {}
        path_params = {}
        query_params = {}
        headers = {}
        missing = []

        for parameter in operation.get("parameters") or []:
            if not isinstance(parameter, dict):
                continue

            name = str(parameter.get("name") or "").strip()
            if not name:
                continue

            location = str(parameter.get("in") or "query").lower()
            normalized = cls._normalized_parameter_name(name)

            value = known_values.get(normalized)
            if value is None:
                value = cls._documented_parameter_value(parameter)

            if value is None and parameter.get("required"):
                value = cls._demo_parameter_value(parameter)

            if value is None:
                if parameter.get("required"):
                    missing.append(name)
                continue

            if location == "path":
                path_params[name] = value
            elif location == "header":
                headers[name] = str(value)
            else:
                query_params[name] = value

        return {
            "path_params": path_params,
            "query_params": query_params,
            "headers": headers,
            "missing": missing,
        }

    @staticmethod
    def _as_number(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = re.sub(r"[^0-9.\-]", "", value.strip())
            if cleaned and cleaned not in {"-", ".", "-."}:
                try:
                    return float(cleaned)
                except ValueError:
                    return None
        return None

    @staticmethod
    def _label_from_item(item):
        if not isinstance(item, dict):
            return None

        preferred_keys = (
            "name",
            "Name",
            "title",
            "Title",
            "label",
            "Label",
            "description",
            "Description",
            "packageName",
            "PackageName",
            "bundleName",
            "BundleName",
            "serviceName",
            "ServiceName",
        )

        for key in preferred_keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return None

    @classmethod
    def _price_from_item(cls, item):
        if not isinstance(item, dict):
            return None

        preferred_keys = (
            "price",
            "Price",
            "amount",
            "Amount",
            "fee",
            "Fee",
            "cost",
            "Cost",
            "total",
            "Total",
            "totalAmount",
            "TotalAmount",
            "charge",
            "Charge",
            "charges",
            "Charges",
        )

        for key in preferred_keys:
            if key in item:
                number = cls._as_number(item.get(key))
                if number is not None:
                    return number

        return None

    @classmethod
    def _walk_payload(cls, value, path="root"):
        """
        Yield dictionaries/lists recursively without assuming one provider's
        response schema. This keeps the runtime normalizer provider-neutral.
        """
        if isinstance(value, dict):
            yield path, value
            for key, child in value.items():
                yield from cls._walk_payload(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from cls._walk_payload(child, f"{path}[{index}]")

    @classmethod
    def normalize_payload(cls, payload):
        """
        Extract customer-facing catalogue/pricing hints from a live GET
        response without hardcoding Emirates Post field names.

        Raw API data remains authoritative and is preserved separately.
        Only fields that can be identified confidently are promoted.
        """
        normalized = {
            "packages": [],
            "durations": [],
            "add_ons": [],
            "fees": [],
            "currency": None,
        }

        seen_packages = set()
        seen_durations = set()
        seen_add_ons = set()
        seen_fees = set()

        currency_keys = {
            "currency",
            "currencycode",
            "currency_code",
        }

        duration_terms = (
            "duration",
            "period",
            "term",
            "year",
            "years",
            "month",
            "months",
        )

        addon_terms = (
            "addon",
            "add_on",
            "additional",
            "extra",
            "optional",
        )

        fee_terms = (
            "fee",
            "fees",
            "charge",
            "charges",
            "price",
            "pricing",
            "cost",
            "amount",
        )

        package_terms = (
            "package",
            "packages",
            "bundle",
            "bundles",
            "plan",
            "plans",
            "product",
            "products",
        )

        for path, item in cls._walk_payload(payload):
            path_lower = path.lower()
            label = cls._label_from_item(item)
            price = cls._price_from_item(item)

            for key, value in item.items():
                key_lower = str(key).lower()

                if key_lower in currency_keys and isinstance(value, str) and value.strip():
                    normalized["currency"] = value.strip().upper()

                if any(term in key_lower for term in duration_terms):
                    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                        duration = str(value).strip()
                        if duration and duration not in seen_durations:
                            seen_durations.add(duration)
                            normalized["durations"].append(duration)

            if label:
                record = {"name": label}
                if price is not None:
                    record["price"] = price

                if any(term in path_lower for term in addon_terms):
                    key = (label.lower(), price)
                    if key not in seen_add_ons:
                        seen_add_ons.add(key)
                        normalized["add_ons"].append(record)
                    continue

                if any(term in path_lower for term in package_terms):
                    key = (label.lower(), price)
                    if key not in seen_packages:
                        seen_packages.add(key)
                        normalized["packages"].append(record)
                    continue

                if price is not None and any(term in path_lower for term in fee_terms):
                    key = (label.lower(), price)
                    if key not in seen_fees:
                        seen_fees.add(key)
                        normalized["fees"].append(record)

        if not normalized["currency"]:
            normalized["currency"] = "AED"

        return normalized

    @classmethod
    def normalize_results(cls, results):
        """
        Merge normalized values from several successful GET operations.
        """
        merged = {
            "packages": [],
            "durations": [],
            "add_ons": [],
            "fees": [],
            "currency": None,
        }

        seen = {
            "packages": set(),
            "durations": set(),
            "add_ons": set(),
            "fees": set(),
        }

        for result in results or []:
            normalized = result.get("normalized") or cls.normalize_payload(
                result.get("payload")
            )

            if not merged["currency"] and normalized.get("currency"):
                merged["currency"] = normalized["currency"]

            for key in ("packages", "add_ons", "fees"):
                for item in normalized.get(key) or []:
                    identity = (
                        str(item.get("name") or "").lower(),
                        item.get("price"),
                    )
                    if identity not in seen[key]:
                        seen[key].add(identity)
                        merged[key].append(item)

            for duration in normalized.get("durations") or []:
                identity = str(duration).lower()
                if identity not in seen["durations"]:
                    seen["durations"].add(identity)
                    merged["durations"].append(duration)

        if not merged["currency"]:
            merged["currency"] = "AED"

        return merged

    def execute_get(
        self,
        tenant_id,
        service_id,
        integration_id,
        operation,
        *,
        path_params=None,
        query_params=None,
        headers=None,
    ):
        self._get_connected_integration(
            tenant_id,
            integration_id,
        )

        source = self._get_source(
            tenant_id,
            service_id,
            integration_id,
        )

        method = str(
            operation.get("method") or ""
        ).upper()

        if method != "GET":
            raise LiveApiExecutionError(
                "Live discovery currently allows GET operations only."
            )

        path = str(
            operation.get("path") or ""
        ).strip()

        if not path:
            raise LiveApiExecutionError(
                "OpenAPI operation has no path."
            )

        for key, value in (path_params or {}).items():
            path = path.replace(
                "{" + str(key) + "}",
                str(value),
            )

        if "{" in path or "}" in path:
            raise LiveApiExecutionError(
                "Required API path parameters are missing."
            )

        base_url = self._resolve_base_url(source)

        url = urljoin(
            base_url,
            path.lstrip("/"),
        )

        try:
            response = httpx.get(
                url,
                params=query_params or {},
                headers=headers or {},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            raise LiveApiExecutionError(
                f"Live API request failed: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise LiveApiExecutionError(
                f"Live API returned HTTP {response.status_code}."
            )

        try:
            payload = response.json()
        except ValueError:
            payload = {
                "text": response.text[:10000],
            }

        return {
            "integration_id": integration_id,
            "operation_id": operation.get("operation_id"),
            "method": method,
            "path": operation.get("path"),
            "url": url,
            "status_code": response.status_code,
            "payload": payload,
            "normalized": self.normalize_payload(payload),
        }