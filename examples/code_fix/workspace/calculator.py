"""Small calculator helpers.

`divide` normalizes zero-denominator failures to ``ValueError`` so callers can
handle invalid user input through the same path regardless of numeric type.
"""


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    """Return ``a / b`` or raise ``ValueError`` for zero denominators.

    The explicit ``b == 0`` guard catches numeric types such as ``Decimal`` that
    represent zero but may not raise ``ZeroDivisionError`` until the operation
    executes. The fallback keeps the calculator behavior stable for any other
    number type that signals zero division via Python's usual exception.
    """
    if b == 0:
        raise ValueError("division by zero")

    try:
        return a / b
    except ZeroDivisionError as exc:
        raise ValueError("division by zero") from exc
