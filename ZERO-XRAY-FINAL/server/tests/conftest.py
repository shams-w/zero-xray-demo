"""Test-only auth configuration.

These are non-production fixtures so runtime code never needs a bundled shared
credential. Real/local credentials are supplied through the ignored .env file.
"""

import os

os.environ.setdefault("ZX_AUTH_PROVIDER", "demo")
os.environ.setdefault("ZX_DEMO_DEV_PASSPHRASE", "zxr-demo-2026")
os.environ.setdefault("ZX_EMPLOYEE_SESSION_TTL_SECONDS", "28800")
