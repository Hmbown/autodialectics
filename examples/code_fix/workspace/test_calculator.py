from decimal import Decimal

import pytest
from calculator import divide


class TestDivide:
    def test_positive_by_zero_raises(self):
        with pytest.raises(ValueError, match="division by zero"):
            divide(10, 0)

    def test_negative_by_zero_raises(self):
        with pytest.raises(ValueError, match="division by zero"):
            divide(-7, 0)

    def test_zero_by_zero_raises(self):
        with pytest.raises(ValueError, match="division by zero"):
            divide(0, 0)

    def test_zero_as_float_raises(self):
        with pytest.raises(ValueError, match="division by zero"):
            divide(5, 0.0)

    def test_expression_result_zero_raises(self):
        """Divisor computed to zero via an expression should still be caught."""
        with pytest.raises(ValueError, match="division by zero"):
            divide(1, 3 - 3)

    def test_decimal_zero_raises(self):
        with pytest.raises(ValueError, match="division by zero"):
            divide(Decimal("5"), Decimal("0"))

    def test_negative_zero_float_raises(self):
        with pytest.raises(ValueError, match="division by zero"):
            divide(8, -0.0)

    def test_normal_division(self):
        assert divide(10, 2) == 5.0

    def test_negative_division(self):
        assert divide(-9, 3) == -3.0

    def test_float_division(self):
        assert divide(7, 2) == 3.5
