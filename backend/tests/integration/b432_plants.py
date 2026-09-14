"""`B432`'s plant for the INTEGRATION directory (S-7a): run explicitly by `tests/unit/test_b432_network_guard.py`."""
import urllib.request


def test_plant_S7a_an_integration_fetch_swallowed():
    try:
        urllib.request.urlopen("http://198.51.100.7/integration", timeout=2)
    except Exception:  # noqa: BLE001
        pass
