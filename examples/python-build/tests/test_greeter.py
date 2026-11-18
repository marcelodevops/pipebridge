import unittest

from greeter import greet


class GreeterTests(unittest.TestCase):
    def test_greet_includes_name(self):
        # INTENTIONAL FAILURE (evidence branch, do not merge): the expected
        # greeting is deliberately wrong so the Test step fails and the
        # Build steps are skipped.
        self.assertEqual(greet("Ada"), "Hello, World")


if __name__ == "__main__":
    unittest.main()
