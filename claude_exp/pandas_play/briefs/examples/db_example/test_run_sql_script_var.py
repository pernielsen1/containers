"""Tests for PRAGMA script_var in run_sql.py: 'name=value' or
'name=$ENVVAR', referenced later as ${name}.

Run:  python3 -m unittest test_run_sql_script_var -v   (from db_example/)
"""
import os
import unittest

from test_run_sql_print import PrintCase


class TestScriptVar(PrintCase):
    def run_with_env(self, sql, **env):
        return self.run_script(sql, env={**os.environ, **env})

    def test_literal_value(self):
        r = self.run_script("PRAGMA script_var = 'who=world';\nPRAGMA print = 'hello ${who}';\nSELECT 1;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hello world", r.stdout)

    def test_env_value(self):
        r = self.run_with_env("PRAGMA script_var = 'd=$MY_TEST_DIR';\nPRAGMA print = 'at ${d}';\nSELECT 1;",
                              MY_TEST_DIR="/some/where")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("at /some/where", r.stdout)

    def test_not_expanded_in_sql(self):
        r = self.run_script("PRAGMA script_var = 'n=42';\nSELECT ${n} AS x;")
        self.assertNotEqual(r.returncode, 0)
        r = self.run_script("PRAGMA script_var = 'n=1 UNION SELECT 2';\nSELECT '${n}' AS x;")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("${n}", r.stdout)

    def test_used_in_export_path(self):
        r = self.run_script(f"PRAGMA script_var = 'd={self.dir}';\nSELECT 1 AS x;\nPRAGMA export = '${{d}}/o.csv';")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.dir / "o.csv").exists())

    def test_unset_env_is_error(self):
        env = {k: v for k, v in os.environ.items() if k != "NOPE_NOT_SET"}
        r = self.run_script("PRAGMA script_var = 'd=$NOPE_NOT_SET';\nSELECT 1;", env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("NOPE_NOT_SET", r.stderr)

    def test_undefined_reference_is_error(self):
        r = self.run_script("PRAGMA print = '${missing}';\nSELECT 1;")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("missing", r.stderr)

    def test_var_used_in_another_var(self):
        r = self.run_script(f"PRAGMA script_var = 'd={self.dir}';\n"
                            "PRAGMA script_var = 'f = ${d}/nested.csv';\n"
                            "SELECT 1 AS x;\nPRAGMA export = '${f}';")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.dir / "nested.csv").exists())

    def test_var_chain_and_env_in_var(self):
        r = self.run_with_env("PRAGMA script_var = 'a=$MY_TEST_DIR';\nPRAGMA script_var = 'b=${a}/x';\n"
                              "PRAGMA script_var = 'c=${b}/y';\nPRAGMA print = 'at ${c}';\nSELECT 1;",
                              MY_TEST_DIR="/some/where")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("at /some/where/x/y", r.stdout)

    def test_undefined_var_in_var_is_error(self):
        r = self.run_script("PRAGMA script_var = 'f=${nope}/x.csv';\nSELECT 1;")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("nope", r.stderr)

    def test_reference_in_comment_ignored(self):
        r = self.run_script("-- note ${missing}\nSELECT 7 AS x;")
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
