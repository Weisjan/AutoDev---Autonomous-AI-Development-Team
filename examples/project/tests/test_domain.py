import pytest
from domain import subtotal


def test_subtotal():
    assert subtotal([]) == 0
    assert subtotal([1234, 66]) == 1300


def test_negative_price_rejected():
    with pytest.raises(ValueError):
        subtotal([100, -1])
