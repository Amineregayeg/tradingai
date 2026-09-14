"""`B432`'s plant for a TOP-LEVEL test file (S-7b): run explicitly by `tests/unit/test_b432_network_guard.py`."""
import urllib.request


def test_plant_S7b_a_top_level_fetch_swallowed():
    try:
        urllib.request.urlopen("http://198.51.100.7/top-level", timeout=2)
    except Exception:  # noqa: BLE001
        pass
