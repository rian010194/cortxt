"""Small statistics helpers built on ranges.sum_to."""
from ranges import sum_to


def average_to(n):
    """Return the mean of the integers from 1 to n, inclusive."""
    return sum_to(n) / (n - 1)
