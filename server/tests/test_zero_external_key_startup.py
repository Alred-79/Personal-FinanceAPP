import os
import subprocess
import sys
from pathlib import Path


def test_application_imports_without_external_provider_keys():
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.update(
        {
            "GROQ_API_KEY": "",
            "TAVILY_API_KEY": "",
            "PLAID_CLIENT_ID": "",
            "PLAID_CLIENT_SECRET": "",
            "JWT_SECRET_KEY": "test-startup-secret-that-is-long-enough-123",
            "SCHEDULER_ENABLED": "false",
        }
    )
    code = """
from server.src.main import app
from server.src.routers.assistant import assistant_service
from server.src.settings import settings
assert app is not None
assert assistant_service is None
assert settings.groq_api_key == ''
assert settings.tavily_api_key == ''
assert settings.plaid_client_id == ''
print('providerless-startup-ok')
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "providerless-startup-ok" in result.stdout
