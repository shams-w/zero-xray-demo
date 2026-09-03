"""Persistent published-Agent store (Section 11-13, 42).

Replaces the frontend's `localStorage.getItem('zero-xray:' + agentId)`
as the source of truth for a published service. An Agent here is a
thin, tenant-scoped pointer to an already-PUBLISHED Blueprint plus a
stable public slug; the Blueprint's `analysis_json` stays the single
source of truth for the underlying content so publishing never forks
a second stale copy of the analysis.

Two very different audiences read Agent data, and this module keeps
them on two different code paths so a bug can't leak one into the
other:

* Tenant staff (Build/Publish Agent UI) -- private, tenant-scoped,
  gets the full record.
* The public customer-facing URL (`/service/{tenant_slug}/{agent_slug}`)
  -- anonymous, gets ONLY `sanitize_for_public()`'s allowlisted output.
"""

import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from core.database import connect_database, resolve_database_target, table_columns, is_postgresql, ensure_database_safety


def _now():
    return datetime.now(timezone.utc).isoformat()


def _dumps(value):
    return json.dumps(value, ensure_ascii=False)


def _slugify(text):
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "service"


AGENT_STATUSES = {"DRAFT", "TESTING", "PUBLISHED", "ARCHIVED"}

# Everything the customer-facing published Agent is allowed to see.
# Deliberately excludes internal-only analysis sections such as
# `relevant_standards` (raw government-standards retrieval text),
# `gap_analysis` / `step_compliance` / `simulation` / `metrics` /
# `validation` (the tenant's own internal reasoning and QA detail),
# and anything resembling a raw LLM prompt/response -- none of that
# is needed to run the customer's journey, and it isn't the
# customer's business to see how ZERO X-RAY reasoned about it
# (Section 12).
PUBLIC_AGENT_ALLOWED_KEYS = {
    "service_name",
    "service_name_ar",
    "service_name_en",
    "service",
    "redesign",
    "blueprint_id",
    "blueprint_status",
}


def sanitize_for_public(result: dict) -> dict:
    """Strip an analysis result down to only what the anonymous
    customer-facing published Agent page needs to render and run a
    journey. Unknown/future keys are dropped by default (allowlist,
    not denylist) so a new internal field added later doesn't
    accidentally become public without a deliberate decision here."""
    if not isinstance(result, dict):
        return {}
    return {key: value for key, value in result.items() if key in PUBLIC_AGENT_ALLOWED_KEYS}


class AgentStore:
    """NOTE: assumes `audit_log` (with its `tenant_id`/`actor_user_id`
    columns) already exists on `database_path` -- i.e. a `RuntimeStore`
    for the same path has already been constructed at least once, as
    `main.py` and every test in this project do (RuntimeStore first,
    AgentStore second). AgentStore only manages its own `agents`
    table; it reuses RuntimeStore's audit_log rather than creating a
    second audit mechanism."""

    def __init__(self, database_path):
        self.database_path = database_path
        self._initialize()
        with self._connect() as connection:
            ensure_database_safety(connection, self.database_path)

    def _connect(self):
        return connect_database(self.database_path)

    def _initialize(self):
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    blueprint_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    analysis_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    published_slug TEXT UNIQUE,
                    created_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agents_tenant_id ON agents (tenant_id);
                """
            )

    def _tenant_slug(self, connection, tenant_id):
        row = connection.execute(
            "SELECT slug FROM tenants WHERE id = ?", (tenant_id,)
        ).fetchone()
        return row["slug"] if row else "tenant"

    def publish_agent(self, tenant_id, blueprint, name=None, created_by=None):
        """`blueprint` must already be the caller's own tenant-scoped,
        PUBLISHED Blueprint (fetched via `get_blueprint_for_tenant` +
        `set_blueprint_status(..., "PUBLISHED", ...)` upstream) -- this
        function does not re-check ownership itself, callers must pass
        an already-authorized Blueprint. The Blueprint approval gate
        (DRAFT -> APPROVED -> PUBLISHED) stays exactly as it was
        (Section 34); publishing an Agent is a second, additive step
        on top of an already-published Blueprint, not a replacement
        for that gate.

        `blueprint["service_id"]`/`["analysis_id"]` (Section 4, added
        in runtime_store.py's `link_blueprint_to_service_analysis`)
        are used when present. A Blueprint from before that linkage
        existed has neither -- the Agent falls back to `blueprint["id"]`
        for both, exactly as before, rather than failing to publish."""
        if blueprint["status"] != "PUBLISHED":
            raise ValueError("The Blueprint must be published before its Agent can be published.")

        agent_id = str(uuid4())
        now = _now()
        display_name = name or f"{blueprint['service_name']} Agent"
        service_id = blueprint.get("service_id") or blueprint["id"]
        analysis_id = blueprint.get("analysis_id") or blueprint["id"]

        with self._connect() as connection:
            tenant_slug = self._tenant_slug(connection, tenant_id)
            base_slug = _slugify(blueprint["service_name"])
            slug = f"{tenant_slug}/{base_slug}"
            suffix = 2
            while connection.execute(
                "SELECT id FROM agents WHERE published_slug = ?", (slug,)
            ).fetchone():
                slug = f"{tenant_slug}/{base_slug}-{suffix}"
                suffix += 1

            connection.execute(
                """
                INSERT INTO agents
                (id, tenant_id, blueprint_id, service_id, analysis_id, name,
                 version, status, published_slug, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, 'PUBLISHED', ?, ?, ?, ?)
                """,
                (
                    agent_id, tenant_id, blueprint["id"], service_id, analysis_id,
                    display_name, slug, created_by, now, now,
                ),
            )
            # Section 21: "Agent published" is an explicitly required
            # audit action. Written into the same shared audit_log
            # table RuntimeStore owns (same db file) rather than
            # duplicating an audit mechanism.
            connection.execute(
                """
                INSERT INTO audit_log
                (id, entity_type, entity_id, action, details_json, created_at,
                 tenant_id, actor_user_id)
                VALUES (?, 'agent', ?, 'PUBLISHED', ?, ?, ?, ?)
                """,
                (
                    str(uuid4()), agent_id,
                    _dumps({"blueprint_id": blueprint["id"], "published_slug": slug}),
                    now, tenant_id, created_by,
                ),
            )
        return self.get_agent_for_tenant(agent_id, tenant_id)

    def get_agent_for_tenant(self, agent_id, tenant_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agents WHERE id = ? AND tenant_id = ?",
                (agent_id, tenant_id),
            ).fetchone()
        return dict(row) if row else None

    def list_agents_for_tenant(self, tenant_id):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agents WHERE tenant_id = ? ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_agent_by_public_slug(self, tenant_slug, agent_slug):
        """Public lookup path: resolves `(tenant_slug, agent_slug)` ->
        the Agent row. Only ever returns PUBLISHED agents -- a DRAFT/
        TESTING/ARCHIVED Agent is not reachable by its public URL,
        the same way a DRAFT Blueprint isn't reachable by ID today."""
        slug = f"{tenant_slug}/{agent_slug}"
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agents WHERE published_slug = ? AND status = 'PUBLISHED'",
                (slug,),
            ).fetchone()
        return dict(row) if row else None
