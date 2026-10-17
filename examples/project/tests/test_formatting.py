from formatting import format_total


def test_currency_formatting():
    assert format_total(0) == "$0.00"
    assert format_total(1234) == "$12.34"
    assert format_total(101) == "$1.01"
