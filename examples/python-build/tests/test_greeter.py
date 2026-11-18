import unittest

from greeter import greet


class GreeterTests(unittest.TestCase):
    def test_greet_includes_name(self):
        self.assertEqual(greet("Ada"), "Hello, Ada")


if __name__ == "__main__":
    unittest.main()
