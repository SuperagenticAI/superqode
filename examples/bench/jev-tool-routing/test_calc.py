import unittest

from calc import add, multiply


class CalculatorTests(unittest.TestCase):
    def test_add(self) -> None:
        self.assertEqual(add(19, 23), 42)

    def test_multiply(self) -> None:
        self.assertEqual(multiply(6, 7), 42)


if __name__ == "__main__":
    unittest.main()
