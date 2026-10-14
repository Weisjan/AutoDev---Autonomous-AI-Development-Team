import pytest
from pydantic import ValidationError

from autodev.config import AgentConfig


def test_max_iterations_is_capped_at_three() -> None:
    with pytest.raises(ValidationError):
        AgentConfig(max_iterations=4)
