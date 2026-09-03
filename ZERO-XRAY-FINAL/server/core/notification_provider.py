"""Notification-provider abstraction for Monitoring alerts.

No external delivery is configured in this project. The default provider is
therefore intentionally DATABASE_ONLY: AlertStore remains the durable source
of truth and no email/SMS/webhook/push delivery is claimed or simulated.
"""
from abc import ABC, abstractmethod


DATABASE_ONLY = "DATABASE_ONLY"
EMAIL_NOT_CONNECTED = "EMAIL_NOT_CONNECTED"
SMS_NOT_CONNECTED = "SMS_NOT_CONNECTED"
WEBHOOK_NOT_CONNECTED = "WEBHOOK_NOT_CONNECTED"


class NotificationProvider(ABC):
    @abstractmethod
    def notify_alert(self, alert: dict) -> dict:
        """Handle a newly-created alert without changing the Alert record."""
        raise NotImplementedError

    @abstractmethod
    def public_status(self) -> dict:
        raise NotImplementedError


class DatabaseOnlyNotificationProvider(NotificationProvider):
    """Default provider. Deliberately performs no external delivery."""

    def notify_alert(self, alert: dict) -> dict:
        return {"state": DATABASE_ONLY, "delivered_externally": False}

    def public_status(self) -> dict:
        return {
            "state": DATABASE_ONLY,
            "email": EMAIL_NOT_CONNECTED,
            "sms": SMS_NOT_CONNECTED,
            "webhook": WEBHOOK_NOT_CONNECTED,
            # Push is an interface placeholder only; no fake connection/state.
            "push_supported": True,
            "external_delivery_configured": False,
        }


# Future providers can implement this interface without changing monitoring or
# alert persistence: EmailNotificationProvider, SmsNotificationProvider,
# WebhookNotificationProvider, PushNotificationProvider.
def get_notification_provider() -> NotificationProvider:
    return DatabaseOnlyNotificationProvider()
