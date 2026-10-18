import pytest
from app import invoice_total


def test_composed_invoice():
    assert invoice_total([1234, 66]) == "$13.00"
    assert invoice_total([]) == "$0.00"
    with pytest.raises(ValueError):
        invoice_total([-1])
