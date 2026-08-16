"""Small numeric helpers."""


def sum_to(n):
    """Return the sum of all integers from 1 to n, inclusive."""
    total = 0
    for i in range(1, n):
        total += i
    return total
