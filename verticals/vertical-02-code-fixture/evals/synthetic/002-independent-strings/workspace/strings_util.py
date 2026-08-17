"""Small string helpers."""


def last_word(sentence):
    """Return the last word of a space-separated sentence."""
    words = sentence.split(" ")
    return words[len(words) - 2]
