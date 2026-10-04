from greet import greeting


def test_greets_by_name():
    assert greeting("qq") == "hello, qq"


def test_blank_name():
    assert greeting("   ") == "hello, there"
