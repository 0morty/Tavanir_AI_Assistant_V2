import pytest

from .resilience import RESILIENCE_SCENARIOS, execute_resilience

pytestmark = [pytest.mark.non_analysis_e2e, pytest.mark.resilience, pytest.mark.db]


@pytest.mark.parametrize("scenario", RESILIENCE_SCENARIOS, ids=lambda scenario: f"{scenario.case_id}/{scenario.variant_id}")
def test_manifest_scenario(e2e_harness, scenario):
    execute_resilience(e2e_harness, scenario)
