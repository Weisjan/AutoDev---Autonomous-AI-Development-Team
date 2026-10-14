from parallel_arithmetic import add, multiply
from parallel_text import slugify


def test_arithmetic():
    assert add(-2, 5) == 3
    assert multiply(-2, 5) == -10
    assert add(0.25, 0.5) == 0.75
    assert multiply(0, 5) == 0


def test_slugify():
    assert slugify(" Hello, World!! ") == "hello-world"
    assert slugify("a___b   c") == "a-b-c"
    assert slugify("123") == "123"
    assert slugify("") == ""
    assert slugify("---") == ""
