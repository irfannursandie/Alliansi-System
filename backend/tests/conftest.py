import os
import pytest
import requests

_BACKEND_UNAVAILABLE_REASON = None


def pytest_configure(config):
    global _BACKEND_UNAVAILABLE_REASON

    base_url = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

    if not base_url:
        _BACKEND_UNAVAILABLE_REASON = (
            "REACT_APP_BACKEND_URL is not set — set it to the backend server URL before running integration tests."
        )
        return

    try:
        response = requests.post(
            f"{base_url}/api/auth/login",
            json={"email": "preflight@check.invalid", "password": "preflight"},
            timeout=5,
        )
        reachable = response.status_code not in (404, 502, 503, 504)
    except requests.exceptions.RequestException:
        reachable = False

    if not reachable:
        _BACKEND_UNAVAILABLE_REASON = (
            f"Backend at {base_url} is not reachable — start the server first."
        )


def pytest_runtest_setup(item):
    if _BACKEND_UNAVAILABLE_REASON is not None:
        test_file = os.path.basename(item.fspath)
        if test_file == "test_raja_api.py":
            pytest.skip(_BACKEND_UNAVAILABLE_REASON)
