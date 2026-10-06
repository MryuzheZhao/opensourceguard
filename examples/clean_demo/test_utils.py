import unittest

from utils import chunk, content_digest, normalise


class UtilsTests(unittest.TestCase):
    def test_digest_is_hex_sha256(self):
        self.assertEqual(len(content_digest(b"abc")), 64)

    def test_normalise_drops_blanks(self):
        self.assertEqual(normalise([" a ", "", "  ", "b"]), ["a", "b"])

    def test_chunk_splits_evenly(self):
        self.assertEqual(chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_chunk_rejects_zero(self):
        with self.assertRaises(ValueError):
            chunk([1], 0)


if __name__ == "__main__":
    unittest.main()
