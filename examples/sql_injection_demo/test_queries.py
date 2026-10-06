import unittest

from queries import connect, find_user_by_id


class QueryTests(unittest.TestCase):
    def test_parameterised_lookup_returns_none_on_empty_db(self):
        connection = connect()
        connection.execute("CREATE TABLE users (id INTEGER, name TEXT, email TEXT)")
        self.assertIsNone(find_user_by_id(connection, 1))

    def test_parameterised_lookup_finds_row(self):
        connection = connect()
        connection.execute("CREATE TABLE users (id INTEGER, name TEXT, email TEXT)")
        connection.execute("INSERT INTO users VALUES (1, 'ada', 'ada@example.com')")
        self.assertEqual(find_user_by_id(connection, 1)[1], "ada@example.com")


if __name__ == "__main__":
    unittest.main()
