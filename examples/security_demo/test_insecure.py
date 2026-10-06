import unittest
from insecure import run_user_command


class ModuleTests(unittest.TestCase):
    def test_demo_module_loads(self):
        self.assertTrue(callable(run_user_command))

