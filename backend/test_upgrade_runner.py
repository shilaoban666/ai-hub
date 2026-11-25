"""Offline runner tests: never import production configuration or connect to MySQL."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / 'backend' / 'migrations'
sys.path.insert(0, str(MIGRATIONS))
import run_upgrade as runner
import upgrade_checks as checks


class UpgradeRunnerTests(unittest.TestCase):
    def invoke(self, args, **patches):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output), patch.multiple(runner, **patches):
            code = runner.main(args)
        return code, output.getvalue()

    def test_preview_is_offline_and_lists_exact_order(self):
        engine = Mock(side_effect=AssertionError('preview opened database'))
        code, output = self.invoke([], configured_engine=engine)
        self.assertEqual(code, 0)
        self.assertIn('no database configuration loaded or connection opened', output)
        self.assertEqual([line.split()[0] for line in output.splitlines() if 'sha256=' in line], list(runner.MIGRATIONS))
        self.assertIn('057_noun_highlight.sql', runner.MIGRATIONS)
        engine.assert_not_called()

    def test_resume_preview_includes_failed_step(self):
        code, output = self.invoke(['--from', '049'], configured_engine=Mock(side_effect=AssertionError()))
        self.assertEqual(code, 0)
        self.assertNotIn('048_agent', output)
        self.assertIn('049_agent_asset_scopes.py', output)
        self.assertIn('053_web_run_hardening.sql', output)

    def test_missing_file_stops_even_when_resuming_later(self):
        with TemporaryDirectory() as empty, redirect_stderr(io.StringIO()):
            with patch.object(runner, 'MIGRATION_DIR', Path(empty)), self.assertRaises(SystemExit) as error:
                runner.main(['--from', '053', '--apply'])
        self.assertEqual(error.exception.code, 2)

    def test_check_cannot_be_combined_with_apply_or_partial_resume(self):
        for args in (['--apply', '--check'], ['--check', '--from', '052']):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                runner.main(args)
            self.assertEqual(error.exception.code, 2)

    def test_check_never_executes_migrations(self):
        engine = Mock()
        code, _ = self.invoke(['--check'], configured_engine=Mock(return_value=engine),
                             verify=Mock(return_value=True), run_sql=Mock(side_effect=AssertionError()))
        self.assertEqual(code, 0)
        engine.dispose.assert_called_once()

    def test_sql_keeps_session_variables_and_consumes_all_results(self):
        engine, connection, cursor = Mock(), Mock(), Mock()
        engine.raw_connection.return_value = connection
        connection.cursor.return_value.__enter__ = Mock(return_value=cursor)
        connection.cursor.return_value.__exit__ = Mock(return_value=False)
        cursor.nextset.side_effect = [True, True, False]
        path = MIGRATIONS / runner.MIGRATIONS[1]
        runner.run_sql(engine, path)
        cursor.execute.assert_called_once_with(path.read_text(encoding='utf-8-sig'))
        self.assertEqual(cursor.nextset.call_count, 3)
        connection.close.assert_called_once()

    def test_sql_result_failure_still_closes_connection(self):
        engine, connection, cursor = Mock(), Mock(), Mock()
        engine.raw_connection.return_value = connection
        connection.cursor.return_value.__enter__ = Mock(return_value=cursor)
        connection.cursor.return_value.__exit__ = Mock(return_value=False)
        cursor.nextset.side_effect = RuntimeError('test')
        with self.assertRaises(RuntimeError):
            runner.run_sql(engine, MIGRATIONS / runner.MIGRATIONS[0])
        connection.close.assert_called_once()

    def test_apply_orders_sql_and_python_and_checks_before_and_after(self):
        engine = Mock()
        events = []
        def verify(_engine, **kw):
            events.append('baseline' if kw.get('baseline') else 'postcheck')
            return True
        def script(command, **kw):
            self.assertEqual(command[0], sys.executable)
            self.assertEqual(command[-1], '--apply')
            self.assertEqual(kw, {'cwd': str(runner.BACKEND_DIR), 'check': True})
            events.append(Path(command[1]).name)
        with patch.object(runner.subprocess, 'run', side_effect=script):
            code, _ = self.invoke(['--apply'], configured_engine=Mock(return_value=engine), verify=verify,
                                 run_sql=lambda _engine, path: events.append(path.name))
        self.assertEqual(code, 0)
        self.assertEqual(events, ['baseline', *runner.MIGRATIONS, 'postcheck'])
        engine.dispose.assert_called_once()

    def test_failure_stops_at_step_and_redacts_details(self):
        engine = Mock()
        calls = []
        def fail(_engine, path):
            calls.append(path.name)
            if path.name.startswith('045'):
                raise RuntimeError('secret-database-credential')
        code, output = self.invoke(['--apply'], configured_engine=Mock(return_value=engine),
                                  verify=Mock(return_value=True), run_sql=fail)
        self.assertEqual(code, 1)
        self.assertEqual(calls, list(runner.MIGRATIONS[:2]))
        self.assertIn('--from 045 --apply', output)
        self.assertNotIn('secret-database-credential', output)
        engine.dispose.assert_called_once()

    def test_failed_baseline_prevents_writes_and_postcheck_failure_returns_nonzero(self):
        resume_sql_count = sum(name >= '053' and name.endswith('.sql') for name in runner.MIGRATIONS)
        for results, expected_calls in (([False], 0), ([True, False], resume_sql_count)):
            sql = Mock()
            with patch.object(runner.subprocess, 'run'):
                code, _ = self.invoke(['--from', '053', '--apply'], configured_engine=Mock(return_value=Mock()),
                                     verify=Mock(side_effect=results), run_sql=sql)
            self.assertEqual(code, 1)
            self.assertEqual(sql.call_count, expected_calls)

    def test_preview_and_legacy_entry_work_from_unrelated_cwd_without_dependencies(self):
        with TemporaryDirectory() as directory:
            for entry in ('run_upgrade.py', 'run_feature_0928.py'):
                result = subprocess.run([sys.executable, '-S', str(MIGRATIONS / entry)], cwd=directory,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('053_web_run_hardening.sql', result.stdout)


class UpgradeCheckTests(unittest.TestCase):
    def setUp(self):
        # Import only metadata; DATABASE_URL is forced to SQLite by the test command.
        from models import Base
        self.metadata = Base.metadata
        self.inspector = Mock()
        self.inspector.has_table.return_value = True
        self.inspector.get_columns.side_effect = lambda table: [
            {'name': name, **({'computed': {'sqltext': '(coalesce(`agent_id`,0))', 'persisted': True}}
                              if name == 'scope_agent_id' and table in ('user_workspaces', 'runtime_cells') else {})}
            for name in Base.metadata.tables[table].columns.keys()
        ]
        self.inspector.get_indexes.side_effect = lambda table: [
            {'name': name, 'unique': unique, 'column_names': columns}
            for name, (unique, columns) in checks.INDEXES.get(table, {}).items()
        ]

    def test_complete_schema_and_backfills_pass_read_only(self):
        with patch('sqlalchemy.inspect', return_value=self.inspector):
            self.assertEqual(checks.schema_problems(Mock()), [])
        connection = Mock()
        connection.exec_driver_sql.return_value.scalar.return_value = 0
        self.assertEqual(checks.data_problems(connection), [])
        self.assertTrue(all(call.args[0].lstrip().startswith('SELECT') for call in connection.exec_driver_sql.call_args_list))

    def test_missing_tables_columns_wrong_indexes_and_generated_columns_fail(self):
        self.inspector.has_table.side_effect = lambda table: table != 'workbench_settings'
        self.inspector.get_columns.side_effect = lambda table: [{'name': name} for name in self.metadata.tables[table].columns.keys() if name != 'idempotency_key']
        self.inspector.get_indexes.return_value = []
        self.inspector.get_indexes.side_effect = None
        with patch('sqlalchemy.inspect', return_value=self.inspector):
            issues = checks.schema_problems(Mock())
        self.assertTrue(any('workbench_settings: table missing' in item for item in issues))
        self.assertTrue(any('missing columns idempotency_key' in item for item in issues))
        self.assertTrue(any('uq_agent_runs_user_idempotency' in item for item in issues))
        self.assertTrue(any('expected stored COALESCE' in item for item in issues))

    def test_baseline_accepts_absent_new_objects_and_does_not_read_data(self):
        self.inspector.has_table.side_effect = lambda table: table not in checks.NEW_TABLES
        self.inspector.get_columns.side_effect = lambda table: [{'name': name} for name in self.metadata.tables[table].columns.keys() if name not in checks.ADDED_COLUMNS.get(table, set())]
        with patch('sqlalchemy.inspect', return_value=self.inspector):
            self.assertEqual(checks.schema_problems(Mock(), baseline=True), [])
        self.inspector.get_indexes.assert_not_called()

    def test_legacy_uniqueness_and_pending_backfills_are_reported(self):
        self.inspector.get_indexes.side_effect = lambda table: [
            {'name': 'legacy_user', 'unique': True, 'column_names': ['user_id']},
        ]
        with patch('sqlalchemy.inspect', return_value=self.inspector):
            self.assertTrue(any('legacy uniqueness' in item for item in checks.schema_problems(Mock())))
        connection = Mock()
        connection.exec_driver_sql.return_value.scalar.return_value = 3
        issues = checks.data_problems(connection)
        self.assertEqual(len(issues), len(checks.DATA_CHECKS))
        self.assertTrue(all(item.endswith(': 3') for item in issues))

    def test_live_prompt_bindings_do_not_require_legacy_snapshots(self):
        self.assertFalse(any('snapshot_json' in sql for sql in checks.DATA_CHECKS.values()))


if __name__ == '__main__':
    unittest.main()
