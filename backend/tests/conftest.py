"""Pytest configuration ensuring unit/integration tests are isolated from local developer .env credentials."""
import os

# Ensure local .env live provider keys (Termii, Twilio, NIPOST) never leak into automated test runs.
# os.environ takes precedence over DotEnvSettingsSource in pydantic-settings.
os.environ["SMS_PROVIDER"] = "simulated"
os.environ["NIPOST_API_BASE_URL"] = ""
os.environ["NIPOST_API_KEY"] = ""
os.environ["OTP_SECRET_KEY"] = ""
os.environ.setdefault("ENVIRONMENT", "development")
