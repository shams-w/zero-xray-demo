"""Payment execution boundary.

ZERO X-RAY currently supports Sandbox payment only.  This module keeps the
existing demo behaviour behind a small provider interface so a real gateway
can be added later without teaching journey/runtime code to invent gateway
success.  Provider implementations receive only server-owned journey state.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import uuid4

from core.pricing_catalog import calculate_price_breakdown


def _now():
    return datetime.now(timezone.utc).isoformat()


class PaymentValidationError(ValueError):
    pass


class PaymentProvider(ABC):
    name = "ABSTRACT"
    is_real_gateway = False

    @abstractmethod
    def create_payment(self, plan, payment_method, approved=True):
        raise NotImplementedError


class SandboxPaymentProvider(PaymentProvider):
    """Existing Sandbox payment, with server-side amount validation."""

    name = "SANDBOX"
    is_real_gateway = False

    @staticmethod
    def _authoritative_amount(plan):
        if not plan.get("requires_payment"):
            raise PaymentValidationError("Payment is not required for this service journey.")

        # Unknown/unverified fees must never become chargeable merely because
        # an AI/draft plan said payment exists.
        fee_status = str(plan.get("fee_status") or "").upper()
        if fee_status in {"VERIFY", "UNKNOWN", "PENDING"}:
            raise PaymentValidationError(
                "The payment amount is not authoritative yet. Confirm the service fee before payment."
            )

        # A deferred fee becomes authoritative only after the server-side
        # assessment/checkpoint has completed (e.g. Sandbox EMX quote after
        # weighing). Do not replace that assessed amount with package-list math.
        if plan.get("payment_timing") != "BEFORE_EXECUTION":
            checkpoint = plan.get("physical_checkpoint") or {}
            amount = plan.get("fee_amount")
            if checkpoint.get("status") == "COMPLETED" and amount is not None:
                try:
                    amount = float(amount)
                except (TypeError, ValueError) as error:
                    raise PaymentValidationError("The server-side payment amount is invalid.") from error
                if amount < 0:
                    raise PaymentValidationError("The server-side payment amount is invalid.")
                return amount, plan.get("fee_currency") or "AED", "SANDBOX_ASSESSMENT"

        pricing = plan.get("edit_options") or {}
        packages = pricing.get("packages") or []
        if packages:
            # Recalculate from the server-owned pricing catalogue and stored
            # selections instead of trusting a previously rendered total.
            breakdown = calculate_price_breakdown(
                pricing,
                plan.get("selected_package_id"),
                years=plan.get("contract_years") or 1,
                add_on_quantities=plan.get("add_on_quantities") or {},
            )
            amount = breakdown.get("total")
            if amount is None:
                raise PaymentValidationError(
                    "The payment amount is not authoritative yet. Confirm the service fee before payment."
                )
            return float(amount), breakdown.get("currency") or plan.get("fee_currency") or "AED", "SERVER_CATALOG"

        amount = plan.get("fee_amount")
        if amount is None:
            raise PaymentValidationError(
                "The payment amount is not authoritative yet. Confirm the service fee before payment."
            )
        try:
            amount = float(amount)
        except (TypeError, ValueError) as error:
            raise PaymentValidationError("The server-side payment amount is invalid.") from error
        if amount < 0:
            raise PaymentValidationError("The server-side payment amount is invalid.")

        # Deferred Sandbox assessments and explicit minimum/fixed fees are
        # server-created plan values.  They remain Sandbox-only, never a claim
        # that an external gateway or fee service was contacted.
        source = "SANDBOX_ASSESSMENT" if plan.get("payment_timing") != "BEFORE_EXECUTION" else "SERVER_VALIDATED"
        return amount, plan.get("fee_currency") or "AED", source

    def create_payment(self, plan, payment_method, approved=True):
        if not approved:
            raise PaymentValidationError("Payment authorization was not granted.")
        amount, currency, authority = self._authoritative_amount(plan)
        return {
            "reference": f"SBX-{uuid4().hex[:10].upper()}",
            "status": "PAID",
            "method": payment_method,
            "amount": amount,
            "currency": currency,
            "sandbox": True,
            "provider": self.name,
            "real_gateway_execution": False,
            "amount_authority": authority,
            "confirmed_at": _now(),
        }


def get_payment_provider():
    """Current provider. Real gateways are intentionally not configured here."""
    return SandboxPaymentProvider()
