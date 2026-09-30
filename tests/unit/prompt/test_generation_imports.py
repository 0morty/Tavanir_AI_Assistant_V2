"""Public Generation imports must work in a fresh interpreter."""
import subprocess
import sys

import pytest


@pytest.mark.parametrize('statement', [
    'from src.application.prompt import PromptBuilder',
    'from src.application.prompt.prompt_builder import PromptBuilder',
    'from src.application.context import ContextBuilder',
    'from src.application.prompt import SuggestionPromptPreparer',
])
def test_generation_entry_imports_do_not_depend_on_prior_imports(statement):
    result = subprocess.run([sys.executable, '-c', statement], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
