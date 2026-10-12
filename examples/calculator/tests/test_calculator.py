from decimal import Decimal

import pytest

from calculator import add, divide, multiply, subtract


def test_basic_operations() -> None:
    assert add(2, 3) == 5
    assert subtract(10, 7) == 3
    assert multiply(6, 7) == 42
    assert divide(8, 2) == 4


def test_negative_and_float_inputs() -> None:
    assert add(-2, 2.5) == 0.5
    assert subtract(-2, -3) == 1
    assert multiply(-1.5, 4) == -6


def test_decimal_inputs_keep_decimal_result() -> None:
    assert add(Decimal("0.1"), Decimal("0.2")) == Decimal("0.3")
    assert divide(Decimal("1.0"), Decimal("4")) == Decimal("0.25")


def test_divide_by_zero_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        divide(10, 0)
