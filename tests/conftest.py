import pytest

from core.fluids import FluidState
from core.system import default_system


@pytest.fixture
def water20():
    return FluidState("water 20 degC", 20.0, 998.2, 1.0016e-3)


@pytest.fixture
def cfg():
    return default_system()
