"""Phase 2 -- ground Build Agent generation in a Service's ACTUAL linked
Data Sources and Integrations, instead of guessing tools/documents from
keyword matches over the raw analysis JSON (the current client-side
`deriveConfig()` in client/src/components/BuildAgentPage.jsx).

This module is purely additive and READ-ONLY with respect to the existing
analysis pipeline:

- It does not change `redesign.future_steps`, `redesign.required_integrations`,
  or any other field already produced by JourneyBuilderAgent/RedesignAgent.
  Those fields are read verbatim elsewhere (Predict/Simulate/Challenge/
  Evolve/Prevent -- see agents/future_simulation_agent.py's own docstring)
  and must keep seeing exactly what they see today.
- It does not introduce a new step-classification vocabulary. It reuses the
  project's existing ones:
    * step "type": SYSTEM / HUMAN / CUSTOMER (JourneyBuilderAgent /
      RedesignAgent -- SYSTEM is the existing signal for "the agent
      executes this step", see agents/future_simulation_agent.py's
      AUTOMATED_STEP_TYPES = {"SYSTEM"}).
    * step "change_type": KEPT / MERGED / REMOVED / AUTOMATED / NEW.
  A SYSTEM step with no matching, usable Integration is reported as
  "INTEGRATION_REQUIRED" -- the same state name already used by
  core/integration_execution.py's IntegrationExecutionError -- rather than
  inventing a new code.
- It never fabricates an Integration or claims automation capability that
  doesn't exist: a step is only ever mapped to an Integration that is
  already linked to this Service (caller-supplied, already tenant- and
  Service-Owner-scoped -- see main.py's `_validate_service_resources`).
- It never returns credentials: Integration `secret_reference`/`config` and
  Data Source `configuration`/`storage_path` are always stripped before
  anything from here reaches the analysis result (and therefore the AI
  prompt, the Blueprint, logs, or audit details).

The single entry point, `build_agent_capability_map`, returns one new,
top-level, additive dict meant to be attached to the `/api/analyze`
response as `result["agent_capability_map"]`. Nothing here mutates its
inputs.
"""

from __future__ import annotations

# The project's existing signal (JourneyBuilderAgent / RedesignAgent /
# future_simulation_agent.AUTOMATED_STEP_TYPES) for "this future step is
# executed by the agent, not the customer or a human reviewer".
AUTOMATABLE_STEP_TYPES = {"SYSTEM"}

# Fields that must never leave this module, regardless of how they arrived
# on the input dicts (catalog_store rows are already reasonably safe, but
# this is a deliberate, explicit allowlist boundary rather than trusting
# the caller's shape to stay that way forever).
_UNSAFE_INTEGRATION_FIELDS = {"secret_reference", "config", "configuration"}
_UNSAFE_DATA_SOURCE_FIELDS = {"configuration", "storage_path"}


def _drop_unsafe(record, unsafe_fields):
    return {
        key: value
        for key, value in (record or {}).items()
        if key not in unsafe_fields
    }


def build_data_source_grounding(data_sources):
    """Sanitized, traceable summary of the Data Sources actually used to
    build this Agent.

    `data_sources` must already be the tenant+Service-scoped list the
    caller resolved (main.py's `_validate_service_resources`, which also
    applies Service-Owner scoping) -- this function performs no lookup of
    its own and therefore cannot widen scope beyond what was passed in.
    Never includes raw Data Source content/file paths.
    """
    grounding = []
    for source in data_sources or []:
        safe = _drop_unsafe(source, _UNSAFE_DATA_SOURCE_FIELDS)
        grounding.append({
            "id": safe.get("id"),
            "name": safe.get("name"),
            "type": safe.get("type"),
            "status": safe.get("status"),
            "classification": safe.get("classification"),
        })
    return grounding


def build_integration_capabilities(integrations):
    """Sanitized, traceable capability list derived from the Service's
    linked Integrations only.

    The capability label is simply the Integration's own stored
    `type`/`name` -- exactly what whoever configured the Integration
    called it. This module maintains no hardcoded catalog of capability
    names; it can only ever describe capabilities that were actually
    configured. Never includes `secret_reference`/`config`.
    """
    capabilities = []
    for integration in integrations or []:
        safe = _drop_unsafe(integration, _UNSAFE_INTEGRATION_FIELDS)
        status = safe.get("status")
        capabilities.append({
            "id": safe.get("id"),
            "name": safe.get("name"),
            "capability_type": safe.get("type"),
            "status": status,
            # CONNECTED = usable now, subject to the existing execution
            # security in core/integration_execution.py at journey-execution
            # time (this module never executes anything itself).
            "available": status == "CONNECTED",
            # SANDBOX = identifiable as a test/sandbox capability, per
            # Phase 2 spec -- never presented as equivalent to CONNECTED.
            "sandbox": status == "SANDBOX",
        })
    return capabilities




_STRUCTURED_STOP_WORDS = {
    "a", "an", "and", "api", "application", "by", "customer", "for", "from",
    "in", "of", "on", "or", "service", "step", "system", "the", "to", "user",
    "with", "v1", "v2", "get", "post", "put", "patch", "delete",
}

# Phase 10 mapping hardening: OpenAPI operation names are commonly terse
# implementation words (Bundle, Select, UpdatePayment, Save) while the Future
# Journey deliberately uses outcome language ("select subscription plan",
# "process payment", "complete subscription").  These small bilingual concept
# groups bridge that vocabulary gap without inventing an endpoint.  A mapping
# is still accepted only when one imported operation wins uniquely.
_CONCEPT_TERMS = {
    "identity": (
        "identity", "identify", "authentication", "authenticate", "verify", "verification",
        "passwordless", "token", "uae pass", "uaepass", "هوية", "الهوية", "تحقق", "التحقق",
    ),
    "select": (
        "select", "selection", "choose", "choice", "option", "اختيار", "اختر", "يختار",
    ),
    "package": (
        "package", "plan", "bundle", "subscription", "product", "باقة", "الباقة", "اشتراك", "الاشتراك",
    ),
    "pricing": (
        "price", "pricing", "cost", "charge", "charges", "fee", "fees", "amount",
        "سعر", "السعر", "تكلفة", "التكلفة", "رسوم", "الرسوم", "مبلغ", "المبلغ",
    ),
    "payment": (
        "pay", "payment", "paid", "checkout", "دفع", "الدفع", "سداد", "السداد",
    ),
    "save": (
        "save", "submit", "submission", "complete", "completion", "finish", "issue", "create",
        "حفظ", "إرسال", "تقديم", "إتمام", "اكمال", "إكمال", "إصدار",
    ),
    "confirm": (
        "confirm", "confirmation", "approve", "approval", "verify", "verification", "تأكيد", "التأكيد", "اعتماد", "الموافقة", "تحقق", "التحقق",
    ),
    "location": (
        "location", "locations", "branch", "box location", "موقع", "الموقع", "فرع", "الفروع",
    ),
    "availability": (
        "available", "availability", "free box", "free boxes", "vacant", "متاح", "متاحة", "صندوق متاح",
    ),
    "rental": (
        "rent", "rental", "renting", "pobox rent", "استئجار", "إيجار", "تأجير",
    ),
    "renewal": (
        "renew", "renewal", "renewed", "تجديد", "التجديد",
    ),
    "notification": (
        "notify", "notification", "message", "sms", "تنبيه", "إشعار", "اشعار", "رسالة",
    ),
}


def _tokens(value):
    import re
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) >= 3 and token not in _STRUCTURED_STOP_WORDS
    }


def _concepts(value):
    text = str(value or "").lower()
    compact = " ".join(text.replace("_", " ").replace("-", " ").split())
    found = set()
    for concept, terms in _CONCEPT_TERMS.items():
        if any(term in compact for term in terms):
            found.add(concept)
    return found


def _structured_operation_score(step, operation, service_context=""):
    """Conservative deterministic score for an imported OpenAPI operation.

    The original lexical matcher is retained, then strengthened with a small
    bilingual concept layer and service-context affinity.  Context is used only
    to disambiguate imported operations (for example Rental vs Renewal); it can
    never create an operation that is not present in the imported Swagger.

    Deliberately excludes the step's own "reason" field from the matched
    text: "reason" is JourneyBuilderAgent's ordering rationale ("must happen
    before any payment step so..."), not a description of what this step
    itself does, and can mention another step's concept in passing. Verified
    bug: an eligibility-check step whose reason text merely mentioned
    "payment" (as in "before any payment step") was matching the payment
    endpoint instead of staying INTEGRATION_REQUIRED. Only "name"/"action" --
    the step's own stated action -- are used for matching.
    """
    step_text = " ".join(str(step.get(field, "")) for field in ("name", "action"))
    step_tokens = _tokens(step_text)
    step_concepts = _concepts(step_text)
    if not step_tokens and not step_concepts:
        return 0

    op_id = str(operation.get("operation_id") or "")
    path = str(operation.get("path") or "")
    tags = " ".join(str(x) for x in (operation.get("tags") or []))
    summary = str(operation.get("summary") or "")
    description = str(operation.get("description") or "")
    op_text = " ".join((op_id, path, tags, summary, description))
    op_tokens = _tokens(op_text)
    op_concepts = _concepts(op_text)
    overlap = step_tokens & op_tokens
    concept_overlap = step_concepts & op_concepts

    compact_step = "".join(ch for ch in step_text.lower() if ch.isalnum())
    compact_id = "".join(ch for ch in op_id.lower() if ch.isalnum())
    phrase_match = bool(compact_id and len(compact_id) >= 6 and (compact_id in compact_step or compact_step in compact_id))

    # Exact/near-exact operation wording remains the strongest signal.
    score = 100 + len(overlap) if phrase_match else 0

    # Keep the old protection against a single weak lexical keyword.  Concept
    # overlap is allowed to bridge outcome-language to API-language, but action
    # concepts carry more weight than generic nouns.
    if len(overlap) >= 2:
        score = max(score, len(overlap) * 10)
        if _tokens(op_id) & overlap:
            score += 5
        if _tokens(path) & overlap:
            score += 3
        if _tokens(tags) & overlap:
            score += 2

    if concept_overlap:
        action_weight = {
            "identity": 38, "select": 34, "payment": 38, "save": 30,
            "confirm": 22, "pricing": 34, "location": 34,
            "availability": 34, "notification": 34, "package": 24,
        }
        concept_score = sum(action_weight.get(c, 12) for c in concept_overlap)
        # A generic package/confirm concept by itself is too weak to bind.
        if concept_overlap - {"package", "confirm"}:
            score = max(score, concept_score)
        elif len(concept_overlap) >= 2:
            score = max(score, concept_score)

    # Service context is a disambiguator, not a match creator. Example:
    # Rent Personal P.O. Box should prefer /Rental/UpdatePayment over a
    # /Renewal/ProcessPayment operation when both share the payment concept.
    if score > 0 and service_context:
        service_concepts = _concepts(service_context)
        # Do not cross-bind mutually exclusive service flows. A Rent service
        # must not silently use Renewal endpoints (and vice versa) merely
        # because both contain words like pricing/payment. Generic Account or
        # Guest operations remain eligible when they do not declare the wrong
        # flow.
        if "rental" in service_concepts and "renewal" in op_concepts and "rental" not in op_concepts:
            return 0
        if "renewal" in service_concepts and "rental" in op_concepts and "renewal" not in op_concepts:
            return 0
        if "rental" in service_concepts and "rental" in op_concepts:
            score += 50
        if "renewal" in service_concepts and "renewal" in op_concepts:
            score += 50

    return max(score, 0)


def _find_structured_operation_match(step, api_operations, service_context=""):
    scored = []
    for operation in api_operations or []:
        if not isinstance(operation, dict) or not operation.get("enabled", True):
            continue
        score = _structured_operation_score(step, operation, service_context=service_context)
        if score > 0:
            scored.append((score, operation))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score = scored[0][0]
    best = [operation for score, operation in scored if score == best_score]
    if len(best) != 1:
        return None
    return best[0]

def _safe_operation(operation):
    return {
        "operation_id": operation.get("operation_id"),
        "method": operation.get("method"),
        "path": operation.get("path"),
        "environment": operation.get("environment"),
    }


def _integration_matches_step(step, integration):
    """Conservative, deterministic overlap between a future step's own
    text and an Integration's own stored name/type -- no invented mapping.
    If nothing overlaps, no match is returned, and the step is reported as
    INTEGRATION_REQUIRED rather than guessed at.
    """
    # Excludes "reason" for the same cause as _structured_operation_score
    # above: it is ordering rationale, not the step's own action, and can
    # mention another step's concept in passing.
    haystack = " ".join(
        str(step.get(field, "")) for field in ("name", "action")
    ).lower()
    if not haystack.strip():
        return False
    for field in ("name", "capability_type"):
        needle = str(integration.get(field, "")).strip().lower()
        if needle and needle in haystack:
            return True
    return False


def _reason_for_not_applicable(step_type):
    """Concise, deterministic, audit-friendly rationale for a step this
    module never treats as agent-executable. No model output, no
    chain-of-thought -- a fixed sentence per the project's own existing
    step_type vocabulary (CUSTOMER / HUMAN)."""
    if step_type == "CUSTOMER":
        return "This step requires direct customer interaction."
    if step_type == "HUMAN":
        return "This step requires human or manual processing."
    return "This step is not classified as agent-executable."


def _reason_for_automate(matched_integration):
    """Concise, deterministic rationale for an AUTOMATE decision -- names
    only the safe, already-sanitized integration fields, never a model
    narrative."""
    status = matched_integration.get("status") or (
        "SANDBOX" if matched_integration.get("sandbox") else "CONNECTED"
    )
    name = matched_integration.get("name") or "a configured integration"
    return f"A {status} integration ('{name}') matches this SYSTEM step."


_REASON_INTEGRATION_REQUIRED = "No configured Service Integration provides this capability."


def _find_unavailable_integration_match(step, integration_capabilities):
    """Phase 4, optional traceability aid (spec: 'You may optionally
    include a safe indicator that a matching but unavailable integration
    exists'): a NOT_CONNECTED integration whose stored name/type
    textually matches this step. Never treated as executable and never
    changes capability_status/AUTOMATE eligibility -- purely informational,
    same sanitized shape as a matched_integration, minus nothing extra.
    """
    for integration in integration_capabilities or []:
        if integration.get("available") or integration.get("sandbox"):
            continue
        if _integration_matches_step(step, integration):
            return {
                "id": integration.get("id"),
                "name": integration.get("name"),
                "status": integration.get("status"),
            }
    return None


def map_future_steps_to_capabilities(future_steps, integration_capabilities, api_operations=None, service_context=""):
    """Map Future Journey steps to safe Service-linked capabilities.

    Imported OpenAPI operations are preferred. If no unique conservative
    structured match exists, the exact legacy Integration name/type matcher is
    used unchanged. Missing/unavailable capability remains
    INTEGRATION_REQUIRED.
    """
    mapping = []
    by_id = {item.get("id"): item for item in (integration_capabilities or [])}
    for step in future_steps or []:
        if not isinstance(step, dict):
            continue
        step_type = str(step.get("type", "")).strip().upper()
        entry = {
            "step_number": step.get("step_number"),
            "name": step.get("name"),
            "step_type": step_type,
            "change_type": step.get("change_type"),
        }
        if step_type not in AUTOMATABLE_STEP_TYPES:
            entry["capability_status"] = "NOT_APPLICABLE"
            entry["mapped_integration"] = None
            entry["reason"] = _reason_for_not_applicable(step_type)
            mapping.append(entry)
            continue

        structured = _find_structured_operation_match(step, api_operations, service_context=service_context)
        if structured:
            parent = by_id.get(structured.get("integration_id"))
            if parent and (parent.get("available") or parent.get("sandbox")):
                mapped = {
                    "id": parent.get("id"),
                    "name": parent.get("name"),
                    "status": parent.get("status"),
                    "sandbox": bool(parent.get("sandbox")),
                    "operation": _safe_operation(structured),
                }
                entry["capability_status"] = "AUTOMATE"
                entry["mapped_integration"] = mapped
                entry["reason"] = (
                    "Matched to a discovered OpenAPI operation: "
                    f"{structured.get('method')} {structured.get('path')}"
                    + (f" ({structured.get('operation_id')})" if structured.get('operation_id') else "")
                    + "."
                )
                mapping.append(entry)
                continue
            if parent:
                entry["capability_status"] = "INTEGRATION_REQUIRED"
                entry["mapped_integration"] = None
                entry["reason"] = "A matching OpenAPI operation exists, but its Service Integration is NOT_CONNECTED."
                entry["unavailable_integration_match"] = {
                    "id": parent.get("id"), "name": parent.get("name"),
                    "status": parent.get("status"), "operation": _safe_operation(structured),
                }
                mapping.append(entry)
                continue

        matched = None
        for integration in integration_capabilities or []:
            if not (integration.get("available") or integration.get("sandbox")):
                continue
            if _integration_matches_step(step, integration):
                matched = integration
                break
        if matched:
            entry["capability_status"] = "AUTOMATE"
            entry["mapped_integration"] = {
                "id": matched.get("id"), "name": matched.get("name"),
                "status": matched.get("status"), "sandbox": bool(matched.get("sandbox")),
            }
            entry["reason"] = _reason_for_automate(entry["mapped_integration"])
        else:
            entry["capability_status"] = "INTEGRATION_REQUIRED"
            entry["mapped_integration"] = None
            entry["reason"] = _REASON_INTEGRATION_REQUIRED
            entry["unavailable_integration_match"] = _find_unavailable_integration_match(step, integration_capabilities)
        mapping.append(entry)
    return mapping


def build_capability_summary(data_sources_used, integration_capabilities, step_capability_mapping):
    """Phase 3 -- additive aggregate counts derived ONLY from the Phase 2
    structures above (no new calculation system, no duplicated state).

    Field semantics (see Phase 3 report for the full rationale):
      - used_data_sources: len(data_sources_used) -- Service-linked Data
        Sources actually included in grounding.
      - connected_apis: Integrations with status == CONNECTED only. A
        SANDBOX Integration is deliberately NOT counted here -- the label
        is "Connected APIs", and folding a sandbox/test capability into
        that count would overstate production readiness. SANDBOX
        Integrations are still visible, precisely, via `sandbox_apis`.
      - sandbox_apis: Integrations with status == SANDBOX -- tracked
        separately for internal/future precision; not one of the six
        required display metrics but kept alongside them rather than
        discarded, since it costs nothing to compute from data already in
        hand.
      - automated_steps / total_steps: counts of
        step_capability_mapping entries with capability_status ==
        "AUTOMATE", out of every step actually classified (AUTOMATE +
        INTEGRATION_REQUIRED + NOT_APPLICABLE) -- map_future_steps_to_
        capabilities() already drops non-dict/invalid entries, so no
        extra filtering is needed here.
      - customer_steps / manual_steps: counts of the existing step_type
        values CUSTOMER / HUMAN (JourneyBuilderAgent's own vocabulary --
        no new classification introduced).
      - integration_required: count of capability_status ==
        "INTEGRATION_REQUIRED".
    """
    step_entries = [entry for entry in (step_capability_mapping or []) if isinstance(entry, dict)]

    return {
        "used_data_sources": len(data_sources_used or []),
        "connected_apis": sum(
            1 for item in (integration_capabilities or []) if item.get("status") == "CONNECTED"
        ),
        "sandbox_apis": sum(
            1 for item in (integration_capabilities or []) if item.get("status") == "SANDBOX"
        ),
        "automated_steps": sum(
            1 for entry in step_entries if entry.get("capability_status") == "AUTOMATE"
        ),
        "total_steps": len(step_entries),
        "customer_steps": sum(1 for entry in step_entries if entry.get("step_type") == "CUSTOMER"),
        "manual_steps": sum(1 for entry in step_entries if entry.get("step_type") == "HUMAN"),
        "integration_required": sum(
            1 for entry in step_entries if entry.get("capability_status") == "INTEGRATION_REQUIRED"
        ),
    }


def build_agent_capability_map(service_id, data_sources, integrations, future_steps, api_operations=None, service_context=""):
    """Single entry point: the additive grounding object meant to be
    attached to the analysis result as `agent_capability_map`. Never
    overwrites or duplicates any existing analysis field, and is itself
    excluded from the public/anonymous Agent payload by
    core/agent_store.py's existing PUBLIC_AGENT_ALLOWED_KEYS allowlist
    (an unrecognized key is dropped there by default).
    """
    integration_capabilities = build_integration_capabilities(integrations)
    data_sources_used = build_data_source_grounding(data_sources)
    step_capability_mapping = map_future_steps_to_capabilities(
        future_steps, integration_capabilities, api_operations=api_operations, service_context=service_context
    )
    return {
        "service_id": service_id,
        "data_sources_used": data_sources_used,
        "integration_capabilities": integration_capabilities,
        "step_capability_mapping": step_capability_mapping,
        # Phase 3: additive aggregate counts for the Build Agent UI.
        # Purely derived from the three fields above -- no new lookup, no
        # new persisted state.
        "summary": build_capability_summary(
            data_sources_used, integration_capabilities, step_capability_mapping
        ),
    }
