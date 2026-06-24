import numpy as np
from pytest import approx

from workflow_tools import boundary


def test_rotate_uv():
    """
    Most basic test following the explanation at
    https://github.com/NOAA-GFDL/CEFI-regional-MOM6/pull/94#pullrequestreview-2318247618
    """
    urot, vrot = boundary.rotate_uv(0, 1, np.pi / 2)
    assert approx(urot) == 1.0
    assert approx(vrot) == 0.0
