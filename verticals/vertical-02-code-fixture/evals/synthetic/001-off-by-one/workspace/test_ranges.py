from ranges import sum_to


def test_sum_to_five():
    assert sum_to(5) == 15


def test_sum_to_one():
    assert sum_to(1) == 1
