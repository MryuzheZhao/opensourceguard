import unittest

from pagination import page_count, paginate


class PageCountTests(unittest.TestCase):
    def test_exact_multiple(self):
        self.assertEqual(page_count(20, 10), 2)

    def test_partial_last_page(self):
        self.assertEqual(page_count(21, 10), 3)

    def test_invalid_per_page(self):
        with self.assertRaises(ValueError):
            page_count(10, 0)


class PaginateShapeTests(unittest.TestCase):
    """These pass even with the off-by-one bug; the reproduction test must
    specifically assert that page 1 returns the first slice."""

    def test_returns_at_most_per_page_items(self):
        self.assertLessEqual(len(paginate(list(range(100)), 1, 10)), 10)

    def test_returns_a_list(self):
        self.assertIsInstance(paginate([1, 2, 3], 1, 2), list)


if __name__ == "__main__":
    unittest.main()
