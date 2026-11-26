import base64
import os

# Test configuration must exist before any app module is imported.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("RESEND_API_KEY", "re_test_dummy")
os.environ.setdefault(
    "RESEND_WEBHOOK_SECRET",
    "whsec_" + base64.b64encode(b"test-webhook-secret-key-32bytes!!!!").decode(),
)
os.environ.setdefault("TEMPLATE_DIR", os.path.join(os.path.dirname(__file__), "..", "templates"))
