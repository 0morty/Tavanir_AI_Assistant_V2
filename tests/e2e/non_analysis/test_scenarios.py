"""Opt-in, real TCP/store scenarios; importing this file starts no services."""

import pytest

from .scenarios import NORMAL_SCENARIOS, Scenario, execute_scenario


@pytest.mark.non_analysis_e2e
@pytest.mark.parametrize("scenario", NORMAL_SCENARIOS, ids=lambda scenario: scenario.id)
def test_manifest_scenario(e2e_harness, scenario: Scenario) -> None:
    execute_scenario(e2e_harness, scenario)
