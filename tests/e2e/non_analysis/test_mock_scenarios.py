import pytest

from .mock_scenarios import MOCK_SCENARIOS, execute_mock

pytestmark = [pytest.mark.non_analysis_e2e, pytest.mark.mock_presentation, pytest.mark.db]


@pytest.mark.parametrize("scenario", MOCK_SCENARIOS, ids=lambda scenario: f"{scenario.case_id}/{scenario.variant_id}")
def test_manifest_scenario(e2e_harness, scenario):
    execute_mock(e2e_harness, scenario)
