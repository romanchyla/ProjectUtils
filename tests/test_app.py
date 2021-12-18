# -*- coding: utf-8 -*-

import unittest

from rutils import ProjectWorker


class TestUpdateRecords(unittest.TestCase):
    def test_config(self):
        app = ProjectWorker("test", local_config={"FOO": ["bar", {}]})
        self.assertEqual(app._config["FOO"], ["bar", {}])
        self.assertEqual(app.config["FOO"], ["bar", {}])

    def test_app_task(self):
        class NewWorker(ProjectWorker):
            def foo(self):
                return "bar"

        app = NewWorker("test", local_config={"FOO": ["bar", {}]})

        assert app.foo() == "bar"


if __name__ == "__main__":
    unittest.main()
