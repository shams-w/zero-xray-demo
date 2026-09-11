import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from core.database import connect_database, resolve_database_target, table_columns, is_postgresql, ensure_database_safety

from core.service_classifier import classify_service, service_type_label
from core.pricing_catalog import build_pricing_catalog, calculate_price_breakdown
from core.payment_provider import get_payment_provider
from tenants.repository import TenantRepository
from core.data_paths import get_database_path


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def _read_json(value, fallback=None):
    if not value:
        return {} if fallback is None else fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {} if fallback is None else fallback


class RuntimeStore:
    """Small persistent store for the Sandbox execution runtime.

    SQLite keeps the demo self-contained. The repository boundary makes it
    straightforward to replace this with managed PostgreSQL for deployment.
    """

    def __init__(self, database_path=None):
        packaged_path = Path(__file__).resolve().parent.parent / "data" / "runtime.db"
        if database_path is None and (os.getenv("DATABASE_URL") or "").strip():
            self.database_path = resolve_database_target(None, packaged_path)
        else:
            default_path = get_database_path(packaged_path)
            self.database_path = resolve_database_target(database_path, default_path)
        self._initialize()
        # Phase 1 multi-tenant foundation: adds tenant_id to the
        # pre-existing tables (additive, backward compatible -- see
        # `_migrate_tenant_columns`) and guarantees a default tenant
        # exists so legacy/unassigned rows always have somewhere safe
        # to live instead of being globally visible.
        self._tenant_repository = TenantRepository(database_path=self.database_path)
        self.default_tenant_id = self._tenant_repository.default_tenant_id
        self._migrate_tenant_columns()
        with self._connect() as connection:
            ensure_database_safety(connection, self.database_path)

    def _connect(self):
        return connect_database(self.database_path)

    def _initialize(self):
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS blueprints (
                    id TEXT PRIMARY KEY,
                    service_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    service_json TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS customers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS journeys (
                    id TEXT PRIMARY KEY,
                    blueprint_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    lang TEXT NOT NULL,
                    sandbox INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    plan_version INTEGER NOT NULL,
                    plan_json TEXT NOT NULL,
                    payment_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (blueprint_id) REFERENCES blueprints(id),
                    FOREIGN KEY (customer_id) REFERENCES customers(id)
                );

                CREATE TABLE IF NOT EXISTS journey_events (
                    id TEXT PRIMARY KEY,
                    journey_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (journey_id) REFERENCES journeys(id)
                );

                CREATE TABLE IF NOT EXISTS journey_capabilities (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    journey_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (journey_id) REFERENCES journeys(id),
                    FOREIGN KEY (customer_id) REFERENCES customers(id)
                );
                CREATE INDEX IF NOT EXISTS idx_journey_capabilities_journey
                    ON journey_capabilities (journey_id);
                CREATE INDEX IF NOT EXISTS idx_journey_capabilities_customer
                    ON journey_capabilities (customer_id);
                CREATE INDEX IF NOT EXISTS idx_journey_capabilities_tenant
                    ON journey_capabilities (tenant_id);

                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _migrate_tenant_columns(self):
        """Additive tenant migration for legacy runtime rows.

        Parent resources are backfilled first. Child resources derive their
        tenant from their existing parent relationships instead of blindly
        receiving the default tenant. This keeps startup compatible with the
        cross-tenant safety triggers that may already exist from a prior run.

        If a legacy Journey points at parents from different tenants, its
        tenant remains NULL (quarantined from tenant-scoped reads) rather than
        inventing ownership or weakening tenant isolation. Idempotent and
        non-destructive: safe to run on every startup.
        """
        tables = ("blueprints", "customers", "journeys", "journey_events", "audit_log")
        with self._connect() as connection:
            # Schema first: all runtime tables get the additive tenant column
            # before any data backfill is attempted.
            for table in tables:
                columns = table_columns(connection, table, self.database_path)
                if "tenant_id" not in columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT")

            # Root runtime resources have no tenant-scoped parent from which
            # legacy ownership can be derived, so they safely belong to the
            # explicit default development tenant.
            for table in ("blueprints", "customers", "audit_log"):
                connection.execute(
                    f"UPDATE {table} SET tenant_id = ? WHERE tenant_id IS NULL",
                    (self.default_tenant_id,),
                )

            # A Journey must agree with BOTH of its parents. Deriving ownership
            # this way avoids the old startup failure where an already-installed
            # tenant guard rejected `default_tenant_id` for a Journey whose
            # Blueprint/Customer had already been assigned to another tenant.
            connection.execute(
                """
                UPDATE journeys
                SET tenant_id = (
                    SELECT b.tenant_id
                    FROM blueprints b
                    JOIN customers c ON c.id = journeys.customer_id
                    WHERE b.id = journeys.blueprint_id
                      AND b.tenant_id IS NOT NULL
                      AND b.tenant_id = c.tenant_id
                )
                WHERE tenant_id IS NULL
                  AND EXISTS (
                    SELECT 1
                    FROM blueprints b
                    JOIN customers c ON c.id = journeys.customer_id
                    WHERE b.id = journeys.blueprint_id
                      AND b.tenant_id IS NOT NULL
                      AND b.tenant_id = c.tenant_id
                  )
                """
            )

            # Events inherit the already-resolved Journey tenant. Ambiguous /
            # quarantined Journeys therefore keep their legacy events hidden too.
            connection.execute(
                """
                UPDATE journey_events
                SET tenant_id = (
                    SELECT j.tenant_id FROM journeys j
                    WHERE j.id = journey_events.journey_id
                )
                WHERE tenant_id IS NULL
                  AND EXISTS (
                    SELECT 1 FROM journeys j
                    WHERE j.id = journey_events.journey_id
                      AND j.tenant_id IS NOT NULL
                  )
                """
            )

            for table in tables:
                connection.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant_id ON {table} (tenant_id)"
                )

            # audit_log also gets actor_user_id (Section 21) -- nullable,
            # since plenty of audited actions (e.g. legacy/system-driven
            # ones) have no authenticated actor to attribute.
            audit_columns = table_columns(connection, "audit_log", self.database_path)
            if "actor_user_id" not in audit_columns:
                connection.execute("ALTER TABLE audit_log ADD COLUMN actor_user_id TEXT")

            # Section 4: a Blueprint remembers the first-class Service/Analysis
            # row it came from. Nullable/backward compatible for legacy rows.
            blueprint_columns = table_columns(connection, "blueprints", self.database_path)
            for column in ("service_id", "analysis_id"):
                if column not in blueprint_columns:
                    connection.execute(f"ALTER TABLE blueprints ADD COLUMN {column} TEXT")

    def _audit(self, connection, entity_type, entity_id, action, details=None,
               tenant_id=None, actor_user_id=None):
        """`tenant_id=None` falls back to the default tenant (never
        NULL, matching `_migrate_tenant_columns`'s legacy backfill).
        Call sites that already have a tenant_id in scope (blueprint
        operations, journey creation) pass it explicitly so the audit
        trail is correctly attributed from the moment it's written,
        not just after the next startup's migration backfill."""
        connection.execute(
            """
            INSERT INTO audit_log
            (id, entity_type, entity_id, action, details_json, created_at,
             tenant_id, actor_user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                entity_type,
                entity_id,
                action,
                _json(self._sanitize_audit_details(details or {})),
                _now(),
                tenant_id or self.default_tenant_id,
                actor_user_id,
            ),
        )

    @staticmethod
    def _sanitize_audit_details(value):
        """Remove secret-bearing fields before audit persistence.

        Audit records are operational metadata, never a credential store.
        """
        sensitive = {
            "password", "passphrase", "credential", "credentials",
            "token", "access_token", "refresh_token", "id_token",
            "authorization", "bearer", "api_key", "apikey",
            "secret", "api_secret", "client_secret", "secret_reference",
        }
        if isinstance(value, dict):
            return {
                str(k): RuntimeStore._sanitize_audit_details(v)
                for k, v in value.items()
                if str(k).lower() not in sensitive
            }
        if isinstance(value, (list, tuple)):
            return [RuntimeStore._sanitize_audit_details(v) for v in value]
        return value

    def record_audit(self, tenant_id, actor_user_id, action, entity_type, entity_id, details=None):
        """Append-only audit entry for API/store actions.

        Kept deliberately small so a future SIEM exporter can consume the same
        table without changing today's persistence architecture.
        """
        with self._connect() as connection:
            self._audit(
                connection, entity_type, entity_id, action,
                details=self._sanitize_audit_details(details or {}),
                tenant_id=tenant_id, actor_user_id=actor_user_id,
            )

    def list_audit_log_for_tenant(self, tenant_id, limit=200):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_log WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_blueprint(self, service, analysis, tenant_id=None):
        """`tenant_id=None` preserves the pre-multi-tenant behavior used
        by every existing caller today (falls back to the default/dev
        tenant) -- see Section 39 backward compatibility. Phase 2 wires
        `main.py` to always pass the authenticated caller's tenant_id
        explicitly; at that point this default stops being reachable
        for real traffic."""
        tenant_id = tenant_id or self.default_tenant_id
        requested_id = service.get("blueprint_id")
        now = _now()
        with self._connect() as connection:
            existing = None
            if requested_id:
                existing = connection.execute(
                    "SELECT * FROM blueprints WHERE id = ? AND tenant_id = ?",
                    (requested_id, tenant_id),
                ).fetchone()

            if existing:
                # PHASE 6 (published Agent reproducibility): re-analyzing an
                # already APPROVED/PUBLISHED Blueprint in place must not
                # silently change what an already-published Agent serves at
                # its live public URL (GET /service/{tenant_slug}/{agent_slug}
                # reads this row's status/analysis fresh on every request --
                # see main.py's get_public_service). If the existing row was
                # APPROVED or PUBLISHED, the fresh analysis demotes it back
                # to DRAFT here, in the same update, so the existing
                # DRAFT -> APPROVED -> PUBLISHED gate (set_blueprint_status)
                # is required again before the new content goes live. The
                # public page then correctly 404s (status != PUBLISHED)
                # until an employee explicitly reviews and republishes,
                # instead of quietly serving unreviewed content under a URL
                # a customer may already have. A DRAFT Blueprint being
                # re-analyzed stays DRAFT -- no behavior change for the
                # common edit-before-approval loop.
                previous_status = existing["status"]
                next_status = "DRAFT" if previous_status in {"APPROVED", "PUBLISHED"} else previous_status
                connection.execute(
                    """
                    UPDATE blueprints
                    SET service_name = ?, service_json = ?, analysis_json = ?,
                        status = ?, updated_at = ?
                    WHERE id = ? AND tenant_id = ?
                    """,
                    (
                        service.get("service_name", "Unknown Service"),
                        _json(service),
                        _json(analysis),
                        next_status,
                        now,
                        requested_id,
                        tenant_id,
                    ),
                )
                self._audit(
                    connection,
                    "blueprint",
                    requested_id,
                    "ANALYSIS_REFRESHED",
                    {
                        "lang": service.get("lang", "en"),
                        "previous_status": previous_status,
                        "status_reset_to_draft": next_status != previous_status,
                    },
                    tenant_id=tenant_id,
                )
                blueprint_id = requested_id
            else:
                blueprint_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO blueprints
                    (id, service_name, status, service_json, analysis_json,
                     created_at, updated_at, tenant_id)
                    VALUES (?, ?, 'DRAFT', ?, ?, ?, ?, ?)
                    """,
                    (
                        blueprint_id,
                        service.get("service_name", "Unknown Service"),
                        _json(service),
                        _json(analysis),
                        now,
                        now,
                        tenant_id,
                    ),
                )
                self._audit(
                    connection,
                    "blueprint",
                    blueprint_id,
                    "CREATED",
                    {"protected_steps": service.get("protected_steps", [])},
                    tenant_id=tenant_id,
                )

        return self.get_blueprint(blueprint_id, tenant_id=tenant_id)

    def get_blueprint(self, blueprint_id, tenant_id=None):
        """`tenant_id=None` keeps today's unscoped lookup for existing
        callers (Section 39). Pass `tenant_id` to scope the lookup --
        use `get_blueprint_for_tenant` when the caller must be strictly
        denied (not silently fall through) on a cross-tenant ID guess."""
        with self._connect() as connection:
            if tenant_id is not None:
                row = connection.execute(
                    "SELECT * FROM blueprints WHERE id = ? AND tenant_id = ?",
                    (blueprint_id, tenant_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM blueprints WHERE id = ?",
                    (blueprint_id,),
                ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "service_name": row["service_name"],
            "status": row["status"],
            "service": _read_json(row["service_json"]),
            "analysis": _read_json(row["analysis_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "tenant_id": row["tenant_id"],
            "service_id": row["service_id"],
            "analysis_id": row["analysis_id"],
        }

    def link_blueprint_to_service_analysis(self, blueprint_id, tenant_id, service_id, analysis_id):
        """Section 4: records which first-class Service/Analysis row
        (core/service_store.py) this Blueprint belongs to. Called once
        right after a new Blueprint is created; a re-analysis of an
        existing Blueprint keeps its original service_id and simply
        gets a new Analysis row (a Service can have a history of
        Analyses)."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE blueprints SET service_id = ?, analysis_id = ? WHERE id = ? AND tenant_id = ?",
                (service_id, analysis_id, blueprint_id, tenant_id),
            )
        return self.get_blueprint(blueprint_id, tenant_id=tenant_id)

    def get_blueprint_for_tenant(self, blueprint_id, tenant_id):
        """Strict tenant-scoped lookup for use once endpoints are
        wired through auth (Phase 2): a valid Blueprint UUID belonging
        to another tenant returns None here, the same as an unknown
        ID -- callers should turn that into a 404, never a 403 that
        would confirm the ID exists (Section 10/29)."""
        return self.get_blueprint(blueprint_id, tenant_id=tenant_id)

    def set_blueprint_status(self, blueprint_id, status, tenant_id=None):
        allowed = {"DRAFT", "APPROVED", "PUBLISHED", "ARCHIVED"}
        if status not in allowed:
            raise ValueError("Unsupported Blueprint status.")
        with self._connect() as connection:
            if tenant_id is not None:
                current = connection.execute(
                    "SELECT status FROM blueprints WHERE id = ? AND tenant_id = ?",
                    (blueprint_id, tenant_id),
                ).fetchone()
            else:
                current = connection.execute(
                    "SELECT status FROM blueprints WHERE id = ?",
                    (blueprint_id,),
                ).fetchone()
            if not current:
                return None
            if status == "PUBLISHED" and current["status"] not in {"APPROVED", "PUBLISHED"}:
                raise ValueError("Approve the Blueprint before publishing it.")
            if tenant_id is not None:
                connection.execute(
                    "UPDATE blueprints SET status = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
                    (status, _now(), blueprint_id, tenant_id),
                )
            else:
                connection.execute(
                    "UPDATE blueprints SET status = ?, updated_at = ? WHERE id = ?",
                    (status, _now(), blueprint_id),
                )
            self._audit(
                connection,
                "blueprint",
                blueprint_id,
                status,
                {"previous_status": current["status"]},
                tenant_id=tenant_id,
            )
        return self.get_blueprint(blueprint_id, tenant_id=tenant_id)

    def register_customer(self, name, email, tenant_id=None):
        tenant_id = tenant_id or self.default_tenant_id
        customer_id = str(uuid4())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO customers (id, name, email, created_at, tenant_id) VALUES (?, ?, ?, ?, ?)",
                (customer_id, name.strip(), email.strip().lower(), _now(), tenant_id),
            )
            self._audit(
                connection,
                "customer",
                customer_id,
                "SANDBOX_REGISTERED",
                {"email": email.strip().lower()},
                tenant_id=tenant_id,
            )
        return {"id": customer_id, "name": name.strip(), "email": email.strip().lower(), "tenant_id": tenant_id}

    def get_customer_for_tenant(self, customer_id, tenant_id):
        """Tenant-scoped lookup for staff-side inspection of a
        sandbox customer record -- a cross-tenant real UUID returns
        None, same denial shape as every other resource."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM customers WHERE id = ? AND tenant_id = ?",
                (customer_id, tenant_id),
            ).fetchone()
        return dict(row) if row else None

    def _resolve_blueprint(self, blueprint_id, intent, sandbox):
        if blueprint_id:
            blueprint = self.get_blueprint(blueprint_id)
            if blueprint and (sandbox or blueprint["status"] == "PUBLISHED"):
                return blueprint

        tokens = {
            token
            for token in re.findall(r"[\w\u0600-\u06ff]+", intent.lower())
            if len(token) > 2
        }
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, service_name FROM blueprints WHERE status = 'PUBLISHED'"
            ).fetchall()
        if not rows:
            return None
        best = max(
            rows,
            key=lambda row: len(
                tokens.intersection(
                    set(re.findall(r"[\w\u0600-\u06ff]+", row["service_name"].lower()))
                )
            ),
        )
        return self.get_blueprint(best["id"])

    def _detect_fee(self, service):
        classification = classify_service(service)
        pricing = build_pricing_catalog(service, classification, service.get("lang", "en"))
        packages = pricing.get("packages") or []
        return packages[0].get("price_per_year") if packages else None

    def _extract_package_options(self, service, fee_amount, lang):
        """Build reviewable package choices without inventing a live catalog.

        The corporate P.O. Box values are an explicit demo fixture already
        supplied by the service owner. Other services use only currency values
        detected in the supplied service text.
        """
        classification = classify_service(service)
        service_kind = classification.get("service_kind")
        if service_kind == "INTERNATIONAL_SHIPMENT":
            return [
                {
                    "id": "standard",
                    "name": "ستاندرد" if lang == "ar" else "Standard",
                    "description": (
                        "التوصيل خلال 15 يومًا"
                        if lang == "ar"
                        else "Delivery within 15 days"
                    ),
                    "price_per_year": None,
                },
                {
                    "id": "express",
                    "name": "إكسبريس" if lang == "ar" else "Express",
                    "description": (
                        "التوصيل خلال 2–5 أيام عمل"
                        if lang == "ar"
                        else "Delivery within 2–5 working days"
                    ),
                    "price_per_year": None,
                },
                {
                    "id": "premium",
                    "name": "بريميوم" if lang == "ar" else "Premium",
                    "description": (
                        "التوصيل خلال 1–3 أيام عمل"
                        if lang == "ar"
                        else "Delivery within 1–3 working days"
                    ),
                    "price_per_year": None,
                },
            ]
        if service_kind == "POSTAL_ACTIVITY_LICENSE":
            # AED 100,000 is a statutory annual minimum, not a selectable
            # package or fixed catalogue price.
            return []
        return build_pricing_catalog(service, classification, lang).get("packages", [])

    def _build_edit_options(
        self,
        service,
        classification,
        requires_payment,
        fee_amount,
        lang,
    ):
        archetype = classification.get("service_archetype", "APPLICATION")
        service_kind = classification.get("service_kind", "GENERAL")
        if requires_payment:
            packages = self._extract_package_options(service, fee_amount, lang)
            pricing = build_pricing_catalog(service, classification, lang)
            options = {
                "mode": "PAYMENT",
                "packages": packages,
                "contract_durations": pricing.get("contract_durations", []),
                "auto_renewal_available": pricing.get("auto_renewal_available", False),
                "one_time_fees": pricing.get("one_time_fees", []),
                "add_ons": pricing.get("add_ons", []),
                "tax": pricing.get("tax", {}),
                "catalog_source": pricing.get("catalog_source"),
                "currency": "AED",
            }
            if service_kind == "INTERNATIONAL_SHIPMENT":
                options.update({
                    "fee_model": "WEIGHT_BASED_QUOTE",
                    "pricing_checkpoint": (
                        "يؤكد مندوب EMX الوزن والأبعاد والسعر النهائي بعد استلام الشحنة"
                        if lang == "ar"
                        else "EMX confirms weight, dimensions and the final quote after receiving the item"
                    ),
                })
            elif service_kind == "POSTAL_ACTIVITY_LICENSE":
                options.update({
                    "fee_model": "ANNUAL_REVENUE_PERCENTAGE_WITH_MINIMUM",
                    "fee_policy_label": (
                        "10% سنويًا من إجمالي مبيعات الأنشطة البريدية"
                        if lang == "ar"
                        else "10% annually of total postal-activity sales"
                    ),
                    "minimum_fee": 100000.0,
                    "minimum_fee_label": (
                        "الحد الأدنى 100,000 درهم يُدفع مقدمًا"
                        if lang == "ar"
                        else "AED 100,000 minimum payable upfront"
                    ),
                    "payment_method_label": (
                        "تحويل بنكي"
                        if lang == "ar"
                        else "Bank transfer"
                    ),
                })
            return options
        if archetype in {"COMPLAINT", "DISPUTE_REFUND"}:
            return {
                "mode": "CASE",
                "priorities": ["NORMAL", "HIGH", "URGENT"],
                "resolutions": [
                    "INVESTIGATE_AND_RESPOND",
                    "CORRECT_SERVICE",
                    "REFUND_OR_REMEDY",
                    "HUMAN_FOLLOW_UP",
                ],
            }
        if archetype == "INFORMATION":
            return {
                "mode": "INQUIRY",
                "topics": [
                    "SERVICE_REQUIREMENTS",
                    "FEES",
                    "REQUIRED_DOCUMENTS",
                    "APPLICATION_STATUS",
                    "GENERAL_INQUIRY",
                ],
                "response_channels": [
                    "IN_APP",
                    "EMAIL",
                    "HUMAN_FOLLOW_UP",
                ],
            }
        return {
            "mode": "ACTION",
            "preferences": ["STANDARD", "FASTEST", "ASSISTED"],
        }

    def _special_runtime_actions(self, service_kind, lang):
        is_arabic = lang == "ar"
        if service_kind == "INTERNATIONAL_SHIPMENT":
            rows = [
                (
                    "استرجاع بيانات الشحنة والمستندات والتحقق منها" if is_arabic else "Retrieve and verify shipment data and documents",
                    "يسترجع المساعد بيانات المرسل والمستلم والفاتورة والجمارك من المصادر المصرح بها." if is_arabic else "The agent retrieves sender, recipient, invoice and customs data from authorized sources.",
                    "بيانات ومستندات موثقة" if is_arabic else "Verified data and documents",
                    "PRE_PAYMENT",
                ),
                (
                    "اختيار باقة الشحن وتجهيز الحجز" if is_arabic else "Select the shipping package and prepare booking",
                    "يقارن المساعد الباقات المتاحة ويثبت الاختيار ويحجز الاستلام دون افتراض سعر نهائي." if is_arabic else "The agent compares Standard, Express and Premium, records the choice and books pickup without inventing a final price.",
                    "باقة وحجز استلام محفوظان" if is_arabic else "Saved package and pickup booking",
                    "PRE_PAYMENT",
                ),
                (
                    "تجهيز الإفصاح والجمارك والملصق المبدئي" if is_arabic else "Prepare declaration, customs file and provisional label",
                    "ينشئ المساعد ملف الشحنة والوثائق والملصق المبدئي قبل نقطة الاستلام المادية." if is_arabic else "The agent creates the shipment file, documents and provisional label before physical handoff.",
                    "ملف شحنة جاهز للتسليم" if is_arabic else "Shipment file ready for handoff",
                    "PRE_PAYMENT",
                ),
                (
                    "استلام EMX للشحنة وتأكيد الوزن والأبعاد" if is_arabic else "EMX receives the item and verifies weight and dimensions",
                    "يسلّم المتعامل الشحنة فقط؛ يؤكد المندوب القياسات ويعيد السعر النهائي المعتمد إلى الرحلة." if is_arabic else "The customer only hands over the item; the courier verifies measurements and returns the approved quote.",
                    "عرض سعر صادر من EMX بعد الفحص" if is_arabic else "EMX quote after physical verification",
                    "PRE_PAYMENT",
                ),
                (
                    "تفعيل الشحنة وإصدار رقم التتبع" if is_arabic else "Activate shipment and issue tracking number",
                    "بعد الدفع يفعّل المساعد الملصق ورقم التتبع ويربطهما بالمعاملة." if is_arabic else "After payment, the agent activates the label and tracking number and links them to the journey.",
                    "رقم شحنة وتتبع فعال" if is_arabic else "Active shipment and tracking number",
                    "POST_PAYMENT",
                ),
                (
                    "متابعة الشحنة حتى التسليم" if is_arabic else "Monitor shipment through delivery",
                    "يتابع المساعد أحداث الشحنة ويعالج الاستثناءات ويسلم إثبات التسليم." if is_arabic else "The agent monitors shipment events, handles exceptions and delivers proof of delivery.",
                    "إثبات تسليم ومسار اعتراض" if is_arabic else "Proof of delivery and objection path",
                    "POST_PAYMENT",
                ),
            ]
        elif service_kind == "POSTAL_ACTIVITY_LICENSE":
            rows = [
                ("تحديد الأنشطة واسترجاع بيانات الشركة" if is_arabic else "Identify activities and retrieve company data", "يحدد المساعد الأنشطة ويسترجع بيانات الشركة ومقدم الطلب من المصادر المصرح بها." if is_arabic else "The agent identifies activities and retrieves company and applicant data from authorized sources.", "نطاق ترخيص وبيانات موثقة" if is_arabic else "Verified licence scope and data", "PRE_PAYMENT"),
                ("استرجاع مستندات الترخيص والتحقق منها" if is_arabic else "Retrieve and verify licence documents", "يسترجع الرخصة التجارية وعقد التأسيس والهوية والجواز وعقد الإيجار والموافقات، ويطلب فقط الاستثناء غير المتاح." if is_arabic else "The agent retrieves the trade licence, memorandum, identity, passport, tenancy and approvals, requesting only unavailable exceptions.", "ملف مستندات مكتمل" if is_arabic else "Complete document file", "PRE_PAYMENT"),
                ("تعبئة الطلب وتقديمه ومتابعة المراجعة" if is_arabic else "Populate, submit and monitor the application", "يقدم المساعد الطلب ويتابع مراجعة بريد الإمارات ويستكمل النواقص من الأنظمة المتصلة." if is_arabic else "The agent submits the application, follows Emirates Post review and resolves missing items through connected systems.", "مرجع طلب وسجل متابعة" if is_arabic else "Application reference and follow-up log", "PRE_PAYMENT"),
                ("حساب الرسوم السنوية الصحيحة" if is_arabic else "Calculate the correct annual fee", "يطبق النظام 10% من إجمالي مبيعات الأنشطة البريدية وبحد أدنى 100,000 درهم يُدفع مقدمًا." if is_arabic else "The system applies 10% of total postal-activity sales with AED 100,000 payable upfront as the minimum.", "وعاء رسوم ومعادلة موثقان" if is_arabic else "Verified fee base and calculation", "PRE_PAYMENT"),
                ("إرفاق إيصال التحويل واستلام الرخصة" if is_arabic else "Attach transfer receipt and obtain the licence", "بعد اعتماد التحويل البنكي يرفق المساعد الإيصال وينزّل الرخصة البريدية." if is_arabic else "After bank-transfer authorization, the agent attaches the receipt and downloads the postal licence.", "رخصة بريدية وإيصال مرتبط" if is_arabic else "Postal licence and linked receipt", "POST_PAYMENT"),
                ("إكمال تحديث الرخصة التجارية والتفعيل النهائي" if is_arabic else "Complete trade-licence update and final activation", "ينسق المساعد إضافة الأنشطة، ويرفع الرخصة التجارية المحدثة، ويتابع تأكيد التفعيل." if is_arabic else "The agent coordinates the activity update, uploads the revised trade licence and follows final activation.", "تأكيد التفعيل النهائي" if is_arabic else "Final activation confirmation", "POST_PAYMENT"),
            ]
        else:
            return None
        return [
            {
                "sequence": index,
                "title": title,
                "detail": detail,
                "evidence": evidence,
                "phase": phase,
                "status": "PLANNED",
            }
            for index, (title, detail, evidence, phase) in enumerate(rows, start=1)
        ]

    @staticmethod
    def _grounded_actions_from_capability_mapping(step_capability_mapping):
        """PHASE 5: build the Test Agent action list directly from the
        Phase 2-4 grounded `agent_capability_map.step_capability_mapping`
        instead of the keyword-guessed `redesign.execution_plan`/
        `redesign.future_steps`, so Test Agent walks through the same
        generated Agent decisions Build Agent already displayed.

        Preserves the existing {sequence, title, detail, evidence,
        status} shape unchanged -- the only fields any current frontend
        or backend code reads (see `_build_plan`'s prior fallback and
        client/src/components/LiveAgentPage.jsx). capability_status/
        step_type/mapped_integration are purely additive: they carry
        forward Phase 4's already-sanitized traceability (no
        secret_reference/config, no chain-of-thought -- see
        core/agent_capability_mapper.py) for any caller that wants it,
        without requiring one.

        Returns [] (not None) when `step_capability_mapping` is missing
        or empty, so `_build_plan` falls back to its existing,
        pre-Phase-2 behavior for legacy Blueprints.

        Does not change automation semantics: an INTEGRATION_REQUIRED
        step is surfaced with that same state name as its `status` (the
        project's own existing state, from
        core/integration_execution.py's IntegrationExecutionError
        default) and a concise evidence note -- Test Agent must never
        report it as completed/executed.
        """
        actions = []
        for index, step in enumerate(step_capability_mapping or [], start=1):
            if not isinstance(step, dict):
                continue
            capability_status = step.get("capability_status")
            matched = step.get("mapped_integration")
            if capability_status == "INTEGRATION_REQUIRED":
                status = "INTEGRATION_REQUIRED"
                evidence = "No suitable connected integration is available for this step yet."
            elif matched:
                status = "PLANNED"
                evidence = f"Executed through the {matched.get('name')} integration."
            else:
                status = "PLANNED"
                evidence = "Reviewable execution log"
            actions.append({
                "sequence": index,
                "title": step.get("name") or f"Action {index}",
                "detail": step.get("reason") or "",
                "evidence": evidence,
                "status": status,
                # Additive Phase 4 traceability, safe to ignore by any
                # caller that only reads the fields above.
                "capability_status": capability_status,
                "step_type": step.get("step_type"),
                "mapped_integration": matched,
            })
        return actions

    @staticmethod
    def _grounded_integrations_from_capability_map(agent_capability_map):
        """PHASE 5: the Service's actual, grounded Integration capabilities
        (Phase 2's `integration_capabilities` -- real CONNECTED/SANDBOX/
        NOT_CONNECTED status, tenant/Service-scoped) instead of
        `redesign.required_integrations`'s keyword-guessed, always-
        "PROPOSED" list. Preserves the existing {status, description}
        item shape the frontend already renders (see
        LiveAgentPage.jsx's `item.status`/`item.description`).

        Returns [] (not None) when there is no `agent_capability_map` or
        no integrations in it, so `_build_plan` falls back to
        `redesign.required_integrations` for legacy Blueprints and for
        Services with no linked Integrations at all -- unchanged
        behavior in both cases.
        """
        capabilities = (agent_capability_map or {}).get("integration_capabilities") or []
        return [
            {
                "status": item.get("status"),
                "description": item.get("name") or item.get("capability_type") or "",
            }
            for item in capabilities
            if isinstance(item, dict)
        ]

    def _build_plan(self, blueprint, intent, lang):
        analysis = blueprint["analysis"]
        redesign = analysis.get("redesign", {})
        # PHASE 5: `agent_capability_map` (Phase 2-4) is the grounded
        # source of truth for what Test Agent should show -- the same
        # Service-linked Data Sources/Integrations and step-level
        # AUTOMATE/INTEGRATION_REQUIRED/NOT_APPLICABLE decisions Build
        # Agent already displayed. It is absent on legacy Blueprints
        # created before Phase 2, so every use below falls back to the
        # exact pre-Phase-2 behavior when it is missing or empty --
        # never a crash, never a forced re-analysis.
        agent_capability_map = analysis.get("agent_capability_map") or {}
        detected_classification = classify_service(blueprint["service"])
        classification = {
            **detected_classification,
            **redesign.get(
                "service_classification",
                redesign.get("design_profile", {}),
            ),
        }
        explanation = redesign.get("agent_execution_explanation", {})
        execution_plan = explanation.get("execution_plan", [])
        actions = self._grounded_actions_from_capability_mapping(
            agent_capability_map.get("step_capability_mapping")
        )
        if not actions:
            for index, item in enumerate(execution_plan, start=1):
                actions.append({
                    "sequence": index,
                    "title": item.get("title") or item.get("name") or f"Action {index}",
                    "detail": item.get("assistant_does") or item.get("action") or "",
                    "evidence": item.get("completion_evidence") or "Reviewable execution log",
                    "status": "PLANNED",
                })
        if not actions:
            for index, item in enumerate(redesign.get("future_steps", []), start=1):
                actions.append({
                    "sequence": index,
                    "title": item.get("name", f"Action {index}"),
                    "detail": item.get("assistant_action") or item.get("action", ""),
                    "evidence": item.get("completion_evidence", "Reviewable execution log"),
                    "status": "PLANNED",
                })

        is_arabic = lang == "ar"
        archetype = classification.get("service_archetype", "APPLICATION")
        service_kind = classification.get("service_kind", "GENERAL")
        payment_context = classification.get("payment_context", "UNKNOWN")
        requires_payment = bool(
            classification.get("requires_customer_payment")
        )
        fee_amount = (
            self._detect_fee(blueprint["service"])
            if requires_payment
            else None
        )
        if service_kind == "INTERNATIONAL_SHIPMENT":
            fee_amount = None
        elif service_kind == "POSTAL_ACTIVITY_LICENSE":
            fee_amount = float(classification.get("minimum_fee") or 100000)
        special_actions = self._special_runtime_actions(service_kind, lang)
        if special_actions:
            actions = special_actions
        waiting_times = blueprint["service"].get("waiting_times", [])
        edit_options = self._build_edit_options(
            blueprint["service"],
            classification,
            requires_payment,
            fee_amount,
            lang,
        )
        default_package = (
            edit_options.get("packages", [None])[0]
            if edit_options.get("packages")
            else None
        )
        pricing_breakdown = None
        if (
            requires_payment
            and service_kind not in {"INTERNATIONAL_SHIPMENT", "POSTAL_ACTIVITY_LICENSE"}
        ):
            pricing_breakdown = calculate_price_breakdown(
                edit_options,
                default_package.get("id") if default_package else None,
                years=1,
                add_on_quantities={},
            )
            if pricing_breakdown.get("total") is not None:
                fee_amount = pricing_breakdown["total"]

        if service_kind == "INTERNATIONAL_SHIPMENT":
            recommended_option = (
                "يجهز المساعد بيانات الشحنة والجمارك والحجز أولًا؛ ثم تستلم EMX الشحنة وتؤكد الوزن والأبعاد والسعر النهائي قبل اعتماد الدفع"
                if is_arabic
                else "The agent prepares shipment data, customs and booking first; EMX then receives and measures the item before you approve the final quote"
            )
            expected_outcome = (
                "شحنة دولية مفعلة برقم تتبع ومتابعة حتى إثبات التسليم"
                if is_arabic
                else "An activated international shipment tracked through proof of delivery"
            )
        elif service_kind == "POSTAL_ACTIVITY_LICENSE":
            recommended_option = (
                "يتولى المساعد تجهيز الطلب والمستندات والمتابعة، وتُحسب الرسوم سنويًا بنسبة 10% من مبيعات الأنشطة البريدية وبحد أدنى 100,000 درهم مقدمًا عبر تحويل بنكي"
                if is_arabic
                else "The agent prepares and follows the application; the annual fee is 10% of postal-activity sales with AED 100,000 upfront as the minimum, paid by bank transfer"
            )
            expected_outcome = (
                "رخصة مزاولة الأنشطة البريدية مفعلة مع تحديث الرخصة التجارية وتأكيد نهائي"
                if is_arabic
                else "An activated postal-activity licence with the commercial licence updated and finally confirmed"
            )
        elif archetype == "COMPLAINT":
            recommended_option = (
                "تصنيف الشكوى والأولوية والجهة المختصة ومسار التصعيد جاهزة للمراجعة"
                if is_arabic
                else "Complaint classification, priority, responsible team and escalation path are ready for review"
            )
            expected_outcome = (
                "تسجيل الشكوى وتسليم رقم مرجعي ومتابعتها حتى القرار مع مسار اعتراض"
                if is_arabic
                else "Register the complaint, deliver a reference and follow it through decision with an objection path"
            )
        elif archetype == "DISPUTE_REFUND":
            recommended_option = (
                "مسار الاعتراض أو الاسترداد والأدلة والمعاملة المرتبطة جاهز للمراجعة"
                if is_arabic
                else "The dispute or refund path, evidence and linked transaction are ready for review"
            )
            expected_outcome = (
                "تقديم الاعتراض أو الاسترداد ومتابعته حتى القرار أو إعادة المبلغ"
                if is_arabic
                else "Submit and track the dispute or refund through decision or reimbursement"
            )
        elif archetype == "INFORMATION":
            recommended_option = (
                "المصدر الحكومي المعتمد والإجابة القابلة للتتبع جاهزان"
                if is_arabic
                else "The authoritative government source and traceable answer are ready"
            )
            expected_outcome = (
                f"تسليم نتيجة موثقة وقابلة للتتبع لخدمة {blueprint['service_name']}"
                if is_arabic
                else f"Deliver a sourced and traceable result for {blueprint['service_name']}"
            )
        else:
            recommended_option = (
                "سيؤكد المساعد الخيار الأنسب من كتالوج الخدمة المتصل"
                if is_arabic
                else "The assistant will confirm the best option from the connected service catalog"
            )
            expected_outcome = (
                f"إتمام {blueprint['service_name']} وتسليم نتيجة قابلة للتتبع"
                if is_arabic
                else f"Complete {blueprint['service_name']} and deliver a traceable outcome"
            )

        fee_display = None
        if service_kind == "INTERNATIONAL_SHIPMENT":
            fee_source = (
                "تؤكد EMX السعر النهائي بعد استلام الشحنة والتحقق من الوزن والأبعاد والباقة"
                if is_arabic
                else "EMX confirms the final quote after receiving the item and verifying weight, dimensions and package"
            )
            fee_status = "PENDING_PHYSICAL_VERIFICATION"
            fee_display = (
                "يُحدد بعد استلام الشحنة ووزنها"
                if is_arabic
                else "Confirmed after pickup and weighing"
            )
        elif service_kind == "POSTAL_ACTIVITY_LICENSE":
            fee_source = (
                "10% سنويًا من إجمالي مبيعات الأنشطة البريدية؛ الحد الأدنى 100,000 درهم يُدفع مقدمًا"
                if is_arabic
                else "10% annually of total postal-activity sales; AED 100,000 is the minimum payable upfront"
            )
            fee_status = "MINIMUM_DUE"
            fee_display = (
                "100,000 درهم حد أدنى مقدمًا"
                if is_arabic
                else "AED 100,000 minimum upfront"
            )
        elif requires_payment and fee_amount is not None:
            fee_source = (
                "مذكورة في خطوات الخدمة"
                if is_arabic
                else "Detected in the supplied service"
            )
            fee_status = "REQUIRED"
        elif requires_payment:
            # Payment may be required by the service, but without a server-owned
            # amount/catalog it is not yet safe to present a payable amount.
            # Mark it for verification so the customer UI cannot submit an
            # invalid payment request (and the provider keeps rejecting unknown
            # amounts as a security boundary).
            fee_source = (
                "الدفع مطلوب لكن يجب تأكيد المبلغ من مصدر الرسوم المعتمد قبل الدفع"
                if is_arabic
                else "Payment is required, but the amount must be confirmed from an authoritative fee source before payment"
            )
            fee_status = "VERIFY"
        elif payment_context == "UNKNOWN":
            fee_source = (
                "لم تثبت رسوم في المدخلات؛ يلزم تأكيد مالك الخدمة ولا تُنشأ دفعة تجريبية"
                if is_arabic
                else "No fee was confirmed; service-owner verification is required and no Sandbox payment is created"
            )
            fee_status = "VERIFY"
        elif payment_context == "REFUND_OR_DISPUTE":
            fee_source = (
                "المبلغ موضوع اعتراض أو استرداد وليس دفعة جديدة"
                if is_arabic
                else "Money is the subject of a dispute or refund, not a new payment"
            )
            fee_status = "REFUND_CONTEXT"
        else:
            fee_source = (
                "لا تتطلب هذه الرحلة دفعة من المتعامل"
                if is_arabic
                else "This journey does not require a customer payment"
            )
            fee_status = "NOT_REQUIRED"

        if service_kind == "INTERNATIONAL_SHIPMENT":
            type_label = "شحن دولي" if is_arabic else "International shipment"
        elif service_kind == "POSTAL_ACTIVITY_LICENSE":
            type_label = "ترخيص أنشطة بريدية" if is_arabic else "Postal activity licence"
        else:
            type_label = service_type_label(archetype, lang)

        return {
            "version": 1,
            "service_name": blueprint["service_name"],
            "requested_outcome": intent,
            "recommended_option": recommended_option,
            "actions": actions,
            "service_archetype": archetype,
            "service_kind": service_kind,
            "service_type_label": type_label,
            "service_classification": classification,
            "payment_context": payment_context,
            "requires_payment": requires_payment,
            "payment_verification_required": bool(
                classification.get("payment_verification_required")
            ),
            "payment_evidence": classification.get("payment_evidence", ""),
            "fee_amount": fee_amount,
            "fee_currency": "AED",
            "fee_source": fee_source,
            "fee_status": fee_status,
            "fee_display": fee_display,
            "fee_model": classification.get("fee_model", "FIXED_OR_CATALOG"),
            "payment_timing": classification.get("payment_timing", "BEFORE_EXECUTION"),
            "payment_method": classification.get("payment_method", "DIGITAL_PAYMENT"),
            "payment_provider": classification.get("payment_provider"),
            "annual_fee_rate": classification.get("annual_fee_rate"),
            "minimum_fee": classification.get("minimum_fee"),
            "physical_handoff_required": bool(classification.get("physical_handoff_required")),
            "physical_checkpoint": {
                "status": "PENDING",
                "provider": classification.get("payment_provider"),
            } if classification.get("payment_timing") != "BEFORE_EXECUTION" else None,
            "edit_options": edit_options,
            "selected_package_id": default_package.get("id") if default_package else None,
            "selected_package_name": default_package.get("name") if default_package else None,
            "contract_years": 1 if edit_options.get("contract_durations") else None,
            "add_on_quantities": pricing_breakdown.get("add_on_quantities", {}) if pricing_breakdown else {},
            "pricing_breakdown": pricing_breakdown,
            "auto_renewal": False,
            "total_fee": fee_amount,
            "consent_mode": classification.get("consent_mode", "EXECUTION"),
            "sla": waiting_times or [
                "يُؤكد من اتفاقية مستوى الخدمة المعتمدة"
                if is_arabic
                else "To be confirmed from the approved service SLA"
            ],
            "expected_outcome": expected_outcome,
            "integrations": self._grounded_integrations_from_capability_map(agent_capability_map)
            or redesign.get("required_integrations", []),
            "protected_steps": redesign.get("protected_steps", []),
            "edit_history": [],
            "execution_mode": "SANDBOX",
            "blueprint_status": blueprint["status"],
        }

    def create_journey(self, customer_id, intent, blueprint_id=None, lang="en", sandbox=True):
        with self._connect() as connection:
            customer = connection.execute(
                "SELECT id, tenant_id FROM customers WHERE id = ?", (customer_id,)
            ).fetchone()
        if not customer:
            raise ValueError("Customer session was not found.")

        blueprint = self._resolve_blueprint(blueprint_id, intent, sandbox)
        if not blueprint:
            raise ValueError("No approved service Blueprint matches this request.")
        blueprint_tenant_id = blueprint.get("tenant_id") or self.default_tenant_id
        customer_tenant_id = customer["tenant_id"] or self.default_tenant_id
        if customer_tenant_id != blueprint_tenant_id:
            raise ValueError("Customer and service do not belong to the same tenant.")

        journey_id = str(uuid4())
        plan = self._build_plan(blueprint, intent, lang)
        now = _now()
        # A journey always inherits its tenant from the Blueprint it
        # resolved to -- this is what prevents a journey belonging to
        # Tenant A from ever being backed by Tenant B's Blueprint data.
        journey_tenant_id = blueprint.get("tenant_id") or self.default_tenant_id
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO journeys
                (id, blueprint_id, customer_id, intent, lang, sandbox, state,
                 plan_version, plan_json, payment_json, created_at, updated_at,
                 tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, 'PLAN_READY', 1, ?, '{}', ?, ?, ?)
                """,
                (
                    journey_id,
                    blueprint["id"],
                    customer_id,
                    intent.strip(),
                    lang,
                    1 if sandbox else 0,
                    _json(plan),
                    now,
                    now,
                    journey_tenant_id,
                ),
            )
            self._audit(
                connection,
                "journey",
                journey_id,
                "PLAN_READY",
                {"blueprint_id": blueprint["id"], "plan_version": 1},
                tenant_id=journey_tenant_id,
            )
        return self.get_journey(journey_id)

    def issue_journey_capability(self, journey_id, customer_id, ttl_seconds=None):
        """Issue one opaque public-customer capability for a journey.

        Only the SHA-256 digest is persisted. Issuing a fresh capability
        invalidates previous active capabilities for the same journey so a
        rotated/restarted customer session cannot leave old credentials live.
        """
        ttl_seconds = int(ttl_seconds or os.getenv("ZX_CUSTOMER_SESSION_TTL_SECONDS", "86400"))
        if ttl_seconds <= 0:
            raise ValueError("Customer session TTL must be positive.")

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        expires_at = (now_dt + timedelta(seconds=ttl_seconds)).isoformat()

        with self._connect() as connection:
            journey = connection.execute(
                "SELECT id, customer_id, tenant_id FROM journeys WHERE id = ?",
                (journey_id,),
            ).fetchone()
            if not journey or journey["customer_id"] != customer_id:
                raise ValueError("Journey/customer session mismatch.")

            connection.execute(
                """
                UPDATE journey_capabilities
                SET revoked_at = ?
                WHERE journey_id = ? AND revoked_at IS NULL
                """,
                (now, journey_id),
            )
            connection.execute(
                """
                INSERT INTO journey_capabilities
                (id, tenant_id, journey_id, customer_id, token_hash,
                 expires_at, revoked_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    str(uuid4()),
                    journey["tenant_id"],
                    journey_id,
                    customer_id,
                    token_hash,
                    expires_at,
                    now,
                ),
            )
        return raw_token, expires_at

    def validate_journey_capability(self, journey_id, raw_token):
        """Return the bound journey only for a live matching capability."""
        if not raw_token:
            return None
        token_hash = hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()
        with self._connect() as connection:
            capability = connection.execute(
                """
                SELECT c.*, j.customer_id AS journey_customer_id,
                       j.tenant_id AS journey_tenant_id
                FROM journey_capabilities c
                JOIN journeys j ON j.id = c.journey_id
                WHERE c.journey_id = ? AND c.token_hash = ?
                LIMIT 1
                """,
                (journey_id, token_hash),
            ).fetchone()
        if not capability or capability["revoked_at"]:
            return None
        if not hmac.compare_digest(capability["token_hash"], token_hash):
            return None
        if capability["customer_id"] != capability["journey_customer_id"]:
            return None
        if capability["tenant_id"] != capability["journey_tenant_id"]:
            return None
        try:
            expires_at = datetime.fromisoformat(capability["expires_at"])
        except (TypeError, ValueError):
            return None
        if expires_at <= datetime.now(timezone.utc):
            return None
        return self.get_journey(journey_id, tenant_id=capability["tenant_id"])

    def revoke_journey_capabilities(self, journey_id):
        """Server-side invalidation support for all customer sessions on a journey."""
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE journey_capabilities
                SET revoked_at = ?
                WHERE journey_id = ? AND revoked_at IS NULL
                """,
                (now, journey_id),
            )

    def get_journey(self, journey_id, tenant_id=None):
        """`tenant_id=None` preserves the anonymous customer-facing
        lookup (Section 42 -- a customer fetches their own journey by
        the ID they were handed, no login involved). Pass `tenant_id`
        when the caller is an authenticated tenant staff member: this
        then behaves like every other `_for_tenant` lookup in this
        project -- a journey belonging to another tenant is
        indistinguishable from an unknown ID (None, not an error)."""
        with self._connect() as connection:
            if tenant_id is not None:
                row = connection.execute(
                    "SELECT * FROM journeys WHERE id = ? AND tenant_id = ?",
                    (journey_id, tenant_id),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM journeys WHERE id = ?", (journey_id,)
                ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "blueprint_id": row["blueprint_id"],
            "customer_id": row["customer_id"],
            "intent": row["intent"],
            "lang": row["lang"],
            "sandbox": bool(row["sandbox"]),
            # A Sandbox journey may complete its simulated event sequence, but
            # that must never be interpreted as proof that an external API was
            # called successfully. Real execution remains disabled elsewhere.
            "execution_mode": "SANDBOX" if bool(row["sandbox"]) else "LIVE",
            "external_execution_succeeded": False,
            "state": row["state"],
            "plan_version": row["plan_version"],
            "plan": _read_json(row["plan_json"]),
            "payment": _read_json(row["payment_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "tenant_id": row["tenant_id"],
        }

    def get_journey_for_tenant(self, journey_id, tenant_id):
        """Strict variant, matching the `*_for_tenant` naming used
        elsewhere -- for authenticated staff endpoints where a
        cross-tenant ID guess must always come back as None/404."""
        return self.get_journey(journey_id, tenant_id=tenant_id)
    def apply_live_plan_enrichment(self, journey_id, tenant_id, plan):
        journey = self.get_journey(journey_id, tenant_id=tenant_id)

        if not journey:
            raise ValueError("Journey was not found.")

        if journey["state"] not in {"PLAN_READY", "PLAN_EDITED"}:
            raise ValueError(
                "Live API data cannot update the plan in its current state."
            )

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE journeys
                SET plan_json = ?, updated_at = ?
                WHERE id = ? AND tenant_id = ?
                """,
                (
                    _json(plan),
                    _now(),
                    journey_id,
                    tenant_id,
                ),
            )

            self._audit(
                connection,
                "journey",
                journey_id,
                "LIVE_API_PLAN_ENRICHED",
                {"plan_version": journey["plan_version"]},
                tenant_id=tenant_id,
            )

        return self.get_journey(journey_id, tenant_id=tenant_id)

    def edit_plan(self, journey_id, instruction="", selections=None, tenant_id=None):
        journey = self.get_journey(journey_id, tenant_id=tenant_id)
        if not journey or journey["state"] not in {"PLAN_READY", "PLAN_EDITED"}:
            raise ValueError("This plan cannot be edited in its current state.")
        plan = journey["plan"]
        selections = selections or {}
        instruction = (instruction or "").strip()

        if selections:
            mode = plan.get("edit_options", {}).get("mode", "ACTION")
            if (
                mode == "PAYMENT"
                and plan.get("fee_model") == "ANNUAL_REVENUE_PERCENTAGE_WITH_MINIMUM"
            ):
                minimum_fee = float(plan.get("minimum_fee") or 100000)
                plan["fee_amount"] = max(float(plan.get("fee_amount") or 0), minimum_fee)
                plan["total_fee"] = plan["fee_amount"]
                instruction = (
                    "تطبيق 10% سنويًا من مبيعات الأنشطة البريدية بحد أدنى 100,000 درهم مقدمًا وتحويل بنكي"
                    if journey["lang"] == "ar"
                    else "Apply 10% annually of postal-activity sales with AED 100,000 upfront as the minimum and bank transfer"
                )
            elif mode == "PAYMENT":
                pricing = plan.get("edit_options", {})
                packages = pricing.get("packages", [])
                selected_id = selections.get("selected_package_id")
                selected_package = next(
                    (item for item in packages if item.get("id") == selected_id),
                    packages[0] if packages else None,
                )
                allowed_durations = pricing.get(
                    "contract_durations", []
                )
                years = int(selections.get("contract_years") or 1)
                if allowed_durations and years not in allowed_durations:
                    raise ValueError("Unsupported renewal duration.")
                breakdown = calculate_price_breakdown(
                    pricing,
                    selected_package.get("id") if selected_package else None,
                    years=years,
                    add_on_quantities=selections.get("add_on_quantities") or {},
                )
                total_fee = breakdown.get("total")
                plan["selected_package_id"] = (
                    selected_package.get("id") if selected_package else None
                )
                plan["selected_package_name"] = (
                    selected_package.get("name") if selected_package else None
                )
                plan["contract_years"] = years if allowed_durations else None
                plan["add_on_quantities"] = breakdown.get("add_on_quantities", {})
                plan["pricing_breakdown"] = breakdown
                plan["auto_renewal"] = bool(selections.get("auto_renewal", False))
                plan["fee_amount"] = total_fee
                plan["total_fee"] = total_fee
                package_name = plan.get("selected_package_name") or (
                    "الخيار المحدد" if journey["lang"] == "ar" else "Selected option"
                )
                if journey["lang"] == "ar" and allowed_durations:
                    instruction = f"{package_name} · {years} سنة"
                elif allowed_durations:
                    instruction = f"{package_name} · {years} year(s)"
                elif plan.get("fee_model") == "WEIGHT_BASED_QUOTE":
                    instruction = (
                        f"{package_name} · تؤكد EMX السعر بعد الاستلام والوزن"
                        if journey["lang"] == "ar"
                        else f"{package_name} · EMX confirms the price after pickup and weighing"
                    )
                else:
                    instruction = package_name
                plan["recommended_option"] = instruction
            elif mode == "CASE":
                priority = selections.get("priority", "NORMAL")
                resolution = selections.get(
                    "requested_resolution", "INVESTIGATE_AND_RESPOND"
                )
                plan["case_priority"] = priority
                plan["requested_resolution"] = resolution
                instruction = f"Priority: {priority} · Resolution: {resolution}"
            elif mode == "INQUIRY":
                allowed_topics = plan.get("edit_options", {}).get("topics", [])
                allowed_channels = plan.get("edit_options", {}).get(
                    "response_channels", []
                )
                topic = selections.get("inquiry_topic", "GENERAL_INQUIRY")
                channel = selections.get("response_channel", "IN_APP")
                if topic not in allowed_topics:
                    raise ValueError("Unsupported inquiry topic.")
                if channel not in allowed_channels:
                    raise ValueError("Unsupported response channel.")
                plan["inquiry_topic"] = topic
                plan["response_channel"] = channel
                instruction = (
                    f"موضوع الاستفسار: {topic} · قناة الرد: {channel}"
                    if journey["lang"] == "ar"
                    else f"Inquiry topic: {topic} · Response channel: {channel}"
                )
            else:
                preference = selections.get("execution_preference", "STANDARD")
                plan["execution_preference"] = preference
                instruction = f"Execution preference: {preference}"

        if not instruction:
            raise ValueError("Choose at least one plan change.")
        version = journey["plan_version"] + 1
        plan["version"] = version
        plan.setdefault("edit_history", []).append({
            "version": version,
            "instruction": instruction,
            "selections": selections,
            "created_at": _now(),
        })
        plan["customer_edit_instruction"] = instruction
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE journeys SET state = 'PLAN_EDITED', plan_version = ?,
                    plan_json = ?, updated_at = ? WHERE id = ?
                """,
                (version, _json(plan), _now(), journey_id),
            )
            self._audit(
                connection,
                "journey",
                journey_id,
                "PLAN_EDITED",
                {
                    "plan_version": version,
                    "instruction": instruction,
                    "selections": selections,
                },
                tenant_id=journey.get("tenant_id"),
            )
        return self.get_journey(journey_id, tenant_id=tenant_id)

    def approve_plan(self, journey_id, tenant_id=None):
        journey = self.get_journey(journey_id, tenant_id=tenant_id)
        if not journey or journey["state"] not in {"PLAN_READY", "PLAN_EDITED"}:
            raise ValueError("This plan cannot be approved in its current state.")
        plan = journey["plan"]
        plan["consent_reference"] = f"CNS-{uuid4().hex[:10].upper()}"
        plan["consent_record"] = {
            "mode": plan.get("consent_mode", "EXECUTION"),
            "plan_version": journey["plan_version"],
            "approved_at": _now(),
        }
        with self._connect() as connection:
            connection.execute(
                "UPDATE journeys SET state = 'PLAN_APPROVED', plan_json = ?, updated_at = ? WHERE id = ?",
                (_json(plan), _now(), journey_id),
            )
            self._audit(
                connection,
                "journey",
                journey_id,
                "PLAN_APPROVED",
                {"plan_version": journey["plan_version"]},
                tenant_id=journey.get("tenant_id"),
            )
        return self.get_journey(journey_id, tenant_id=tenant_id)

    def prepare_payment_assessment(self, journey_id, tenant_id=None):
        journey = self.get_journey(journey_id, tenant_id=tenant_id)
        if not journey or journey["state"] != "PLAN_APPROVED":
            raise ValueError("Approve the final plan before the payment assessment.")
        plan = journey["plan"]
        timing = plan.get("payment_timing", "BEFORE_EXECUTION")
        if timing == "BEFORE_EXECUTION":
            raise ValueError("This service does not use a deferred payment assessment.")

        is_arabic = journey["lang"] == "ar"
        checkpoint = plan.get("physical_checkpoint") or {}
        checkpoint.update({
            "status": "COMPLETED",
            "confirmed_at": _now(),
        })

        if plan.get("service_kind") == "INTERNATIONAL_SHIPMENT":
            package_id = plan.get("selected_package_id") or "standard"
            # Demo-only quote returned by the simulated EMX connection. In a
            # production journey the exact value comes from EMX after weighing.
            sandbox_quotes = {
                "standard": 185.0,
                "express": 320.0,
                "premium": 495.0,
            }
            amount = sandbox_quotes.get(package_id, sandbox_quotes["standard"])
            plan["fee_amount"] = amount
            plan["total_fee"] = amount
            plan["fee_status"] = "REQUIRED"
            plan["fee_display"] = (
                f"{amount:,.0f} درهم · عرض تجريبي بعد الوزن"
                if is_arabic
                else f"AED {amount:,.0f} · Sandbox quote after weighing"
            )
            plan["fee_source"] = (
                "عرض تجريبي من محاكاة EMX بعد استلام الشحنة والتحقق من الوزن والأبعاد"
                if is_arabic
                else "Sandbox quote from the simulated EMX connection after pickup and measurement"
            )
            checkpoint["quote_reference"] = f"EMX-SBX-{uuid4().hex[:8].upper()}"
            checkpoint["quote_amount"] = amount
        else:
            minimum_fee = float(plan.get("minimum_fee") or 100000)
            plan["fee_amount"] = max(float(plan.get("fee_amount") or 0), minimum_fee)
            plan["total_fee"] = plan["fee_amount"]
            plan["fee_status"] = "MINIMUM_DUE"
            checkpoint["assessment_reference"] = f"FEE-SBX-{uuid4().hex[:8].upper()}"

        plan["physical_checkpoint"] = checkpoint
        with self._connect() as connection:
            connection.execute(
                "UPDATE journeys SET state = 'AWAITING_PAYMENT', plan_json = ?, updated_at = ? WHERE id = ?",
                (_json(plan), _now(), journey_id),
            )
            self._audit(
                connection,
                "journey",
                journey_id,
                "PAYMENT_ASSESSMENT_READY",
                checkpoint,
                tenant_id=journey.get("tenant_id"),
            )
        return self.get_journey(journey_id, tenant_id=tenant_id)

    def pay(self, journey_id, payment_method, approved=True, tenant_id=None):
        journey = self.get_journey(journey_id, tenant_id=tenant_id)
        if not journey:
            raise ValueError("Journey was not found.")
        deferred = journey["plan"].get("payment_timing") != "BEFORE_EXECUTION"
        required_state = "AWAITING_PAYMENT" if deferred else "PLAN_APPROVED"
        if journey["state"] != required_state:
            raise ValueError("Approve the final plan before payment.")
        # Payment execution is provider-owned. The current provider is the
        # existing Sandbox implementation; it recalculates/validates the
        # authoritative server-side amount and never represents a real gateway
        # call. Unknown/unverified fees are rejected instead of invented.
        payment = get_payment_provider().create_payment(
            journey["plan"], payment_method=payment_method, approved=approved
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE journeys SET state = 'PAID', payment_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (_json(payment), _now(), journey_id),
            )
            self._audit(connection, "journey", journey_id, "PAYMENT_CONFIRMED", payment, tenant_id=journey.get("tenant_id"))
        return self.get_journey(journey_id, tenant_id=tenant_id)

    def start_execution(self, journey_id, tenant_id=None):
        journey = self.get_journey(journey_id, tenant_id=tenant_id)
        if not journey:
            raise ValueError("Journey was not found.")
        requires_payment = bool(journey["plan"].get("requires_payment"))
        required_state = "PAID" if requires_payment else "PLAN_APPROVED"
        if journey["state"] != required_state:
            if requires_payment:
                raise ValueError("Confirmed payment is required before execution.")
            raise ValueError("Approved consent is required before execution.")
        actions = journey["plan"].get("actions", [])
        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT COUNT(*) AS count FROM journey_events WHERE journey_id = ?",
                (journey_id,),
            ).fetchone()["count"]
            if existing == 0:
                for index, action in enumerate(actions, start=1):
                    initial_status = (
                        "COMPLETED"
                        if journey["plan"].get("payment_timing") != "BEFORE_EXECUTION"
                        and action.get("phase") == "PRE_PAYMENT"
                        else "QUEUED"
                    )
                    connection.execute(
                        """
                        INSERT INTO journey_events
                        (id, journey_id, sequence, event_type, title, detail,
                         status, created_at, updated_at)
                         VALUES (?, ?, ?, 'AGENT_ACTION', ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            journey_id,
                            index,
                            action.get("title", f"Action {index}"),
                            action.get("detail", ""),
                            initial_status,
                            now,
                            now,
                        ),
                    )
            connection.execute(
                "UPDATE journeys SET state = 'EXECUTING', updated_at = ? WHERE id = ?",
                (now, journey_id),
            )
            self._audit(connection, "journey", journey_id, "EXECUTION_STARTED", {}, tenant_id=journey.get("tenant_id"))
        return self.get_journey(journey_id, tenant_id=tenant_id)

    def list_events(self, journey_id, tenant_id=None):
        """`tenant_id` is checked against the parent journey first --
        if provided and it doesn't match, no events are returned
        (same 404-shaped denial as everywhere else), rather than
        leaking event titles/details for another tenant's journey."""
        if tenant_id is not None and not self.get_journey(journey_id, tenant_id=tenant_id):
            return []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM journey_events WHERE journey_id = ? ORDER BY sequence",
                (journey_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_event_status(self, event_id, status, tenant_id=None):
        with self._connect() as connection:
            if tenant_id is not None:
                owner_check = connection.execute(
                    """
                    SELECT je.id FROM journey_events je
                    JOIN journeys j ON j.id = je.journey_id
                    WHERE je.id = ? AND j.tenant_id = ?
                    """,
                    (event_id, tenant_id),
                ).fetchone()
                if not owner_check:
                    return False
            connection.execute(
                "UPDATE journey_events SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), event_id),
            )
        return True

    def complete_journey(self, journey_id, tenant_id=None):
        if tenant_id is not None and not self.get_journey(journey_id, tenant_id=tenant_id):
            return None
        # Audit attribution must always use the Journey's OWN tenant_id
        # -- never the caller's tenant_id (which is None for the
        # anonymous customer-facing execution flow) and never a
        # default-tenant fallback. Journey -> tenant_id -> Audit Entry.
        owning_journey = self.get_journey(journey_id)
        with self._connect() as connection:
            update = connection.execute(
                """
                UPDATE journeys SET state = 'COMPLETED', updated_at = ?
                WHERE id = ? AND state = 'EXECUTING'
                """,
                (_now(), journey_id),
            )
            if update.rowcount:
                self._audit(
                    connection, "journey", journey_id, "COMPLETED", {},
                    tenant_id=owning_journey.get("tenant_id") if owning_journey else None,
                )
        return self.get_journey(journey_id, tenant_id=tenant_id)

    def change_journey_state(self, journey_id, state, tenant_id=None):
        if state not in {"PAUSED", "CANCELLED", "HUMAN_HANDOFF"}:
            raise ValueError("Unsupported journey control action.")
        journey = self.get_journey(journey_id, tenant_id=tenant_id)
        if not journey:
            return None
        with self._connect() as connection:
            connection.execute(
                "UPDATE journeys SET state = ?, updated_at = ? WHERE id = ?",
                (state, _now(), journey_id),
            )
            self._audit(connection, "journey", journey_id, state, {}, tenant_id=journey.get("tenant_id"))
        return self.get_journey(journey_id, tenant_id=tenant_id)

    def resume_journey(self, journey_id, tenant_id=None):
        """Resume is only valid from PAUSED, and only back to
        EXECUTING -- a journey that was paused before execution ever
        started (e.g. mid PLAN_READY) has no execution to resume, so
        this deliberately does not try to guess an arbitrary prior
        state. Tenant-scoped the same way as every other journey
        mutation: a cross-tenant journey_id returns None here too."""
        journey = self.get_journey(journey_id, tenant_id=tenant_id)
        if not journey:
            return None
        if journey["state"] != "PAUSED":
            raise ValueError("Only a paused journey can be resumed.")
        with self._connect() as connection:
            connection.execute(
                "UPDATE journeys SET state = 'EXECUTING', updated_at = ? WHERE id = ?",
                (_now(), journey_id),
            )
            self._audit(connection, "journey", journey_id, "RESUMED", {}, tenant_id=journey.get("tenant_id"))
        return self.get_journey(journey_id, tenant_id=tenant_id)
