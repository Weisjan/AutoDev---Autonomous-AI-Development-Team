import pytest


@pytest.mark.parametrize("a,b,expected", [(1, 2, 3), (-2, 5, 3), (0, 0, 0), (0.25, 0.5, 0.75)])
def test_add(a, b, expected):
    from parallel_arithmetic import add

    assert add(a, b) == expected


@pytest.mark.parametrize("a,b,expected", [(2, 3, 6), (-2, 5, -10), (0, 5, 0), (0.5, 0.5, 0.25)])
def test_multiply(a, b, expected):
    from parallel_arithmetic import multiply

    assert multiply(a, b) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        (" Hello, World!! ", "hello-world"),
        ("a___b   c", "a-b-c"),
        ("123", "123"),
        ("", ""),
        ("---", ""),
        ("  A--42__B  ", "a-42-b"),
        ("café", "caf"),
    ],
)
def test_slugify(text, expected):
    from parallel_text import slugify

    assert slugify(text) == expected
