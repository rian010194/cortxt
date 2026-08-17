from strings_util import last_word


def test_last_word():
    assert last_word("the quick brown fox") == "fox"


def test_last_word_single_word():
    assert last_word("hello") == "hello"
