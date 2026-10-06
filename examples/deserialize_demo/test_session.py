import unittest

from session import safe_digest


class DigestTests(unittest.TestCase):
    def test_safe_digest_is_stable(self):
        self.assertEqual(safe_digest("abc"), safe_digest("abc"))

    def test_safe_digest_length(self):
        self.assertEqual(len(safe_digest("abc")), 64)


if __name__ == "__main__":
    unittest.main()
