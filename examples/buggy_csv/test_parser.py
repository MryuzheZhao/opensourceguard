import unittest
from parser import parse_csv


class ParserTests(unittest.TestCase):
    def test_regular_input(self):
        self.assertEqual(parse_csv("a,b"), ["a", "b"])

    def test_multiple_rows(self):
        self.assertEqual(parse_csv("a,b\nc,d"), [["a", "b"], ["c", "d"]])

