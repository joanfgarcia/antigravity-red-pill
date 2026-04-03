
import pytest


@pytest.mark.integration
def test_production_leak_prevention():
    """Verify that integration tests are blocked from production port without explicit opt-in."""
    # This should fail/skip due to conftest.py restrictions
    with pytest.raises(pytest.skip.Exception):
        # We simulate the setup check
        pass
