"""Exercise deployment ordering with fake services; never touch real processes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeploymentScriptTests(unittest.TestCase):
    def run_deploy(self, fail_build=False, fail_ready=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for folder in ('backend', 'frontend/dist/assets', 'venv/bin', 'bin'):
            (root / folder).mkdir(parents=True)
        (root / 'frontend/dist/index.html').write_text('old-index')
        (root / 'frontend/dist/assets/old.js').write_text('old-chunk')
        events = root / 'events'

        def executable(path, body):
            path.write_text('#!/bin/bash\nset -e\n' + body)
            path.chmod(0o755)

        executable(root / 'venv/bin/python', '''
case "$*" in
  *get_configured_sandbox_type*) echo directory ;;
  *--print-channel-state*) echo disabled ;;
  *) echo 'preflight: OK' ;;
esac
''')
        executable(root / 'venv/bin/pip', 'echo dependencies >> "$DEPLOY_EVENTS"\n')
        executable(root / 'venv/bin/uvicorn', 'echo backend-start >> "$DEPLOY_EVENTS"\n')
        executable(root / 'bin/git', 'echo pull >> "$DEPLOY_EVENTS"\n')
        executable(root / 'bin/npm', '''
if [ "$1" = install ]; then exit 0; fi
echo build >> "$DEPLOY_EVENTS"
[ "$FAIL_BUILD" != 1 ] || exit 1
mkdir -p "$5/assets"
echo new-chunk > "$5/assets/new.js"
echo new-index > "$5/index.html"
''')
        script = (ROOT / 'aihub.sh').read_text()
        script = script[script.index('# 路径配置'):script.index('# 主入口')]
        script = script.replace('ROOT_DIR="/var/www/git_repo/aihub"', 'ROOT_DIR="$DEPLOY_ROOT"')
        script = script.replace('VENV_DIR="/var/www/git_repo/aihub-venv"', 'VENV_DIR="$DEPLOY_ROOT/venv"')
        script = 'set -e\n' + script + '''
status_line() { :; }
check_frontend_runtime() { :; }
run_preflight_check() { :; }
port_pid() { echo 424242; }
channel_worker_pid() { echo 434343; }
stop_channel_worker() { echo worker-stop >> "$DEPLOY_EVENTS"; }
stop_backend() { echo backend-stop >> "$DEPLOY_EVENTS"; }
wait_backend_ready() {
  echo ready >> "$DEPLOY_EVENTS"
  [ "$FAIL_READY" != 1 ]
}
# Stub kill for startup failure cleanup; fake PIDs must not signal real processes.
kill() { :; }
do_start
'''
        # Keep the script and logs outside the fake frontend build tree.
        file = root / 'run.sh'
        file.write_text(script)
        result = subprocess.run(['bash', str(file)], env={
            **os.environ, 'PATH': str(root / 'bin') + ':' + os.environ['PATH'],
            'DEPLOY_ROOT': str(root), 'DEPLOY_EVENTS': str(events),
            'FAIL_BUILD': str(int(fail_build)), 'FAIL_READY': str(int(fail_ready)),
        }, capture_output=True, text=True, timeout=10)
        return result, root, events.read_text().splitlines()

    def test_build_before_stop_and_publish_after_ready_keeps_old_chunks(self):
        result, root, events = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLess(events.index('build'), events.index('worker-stop'))
        self.assertLess(events.index('worker-stop'), events.index('backend-stop'))
        self.assertLess(events.index('backend-stop'), events.index('ready'))
        self.assertEqual((root / 'frontend/dist/index.html').read_text().strip(), 'new-index')
        self.assertTrue((root / 'frontend/dist/assets/old.js').exists())
        self.assertTrue((root / 'frontend/dist/assets/new.js').exists())
        self.assertEqual(list((root / 'frontend').glob('.deploy-build.*')), [])

    def test_build_failure_keeps_old_processes_and_frontend(self):
        result, root, events = self.run_deploy(fail_build=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('worker-stop', events)
        self.assertNotIn('backend-stop', events)
        self.assertEqual((root / 'frontend/dist/index.html').read_text(), 'old-index')

    def test_not_ready_does_not_publish_new_frontend(self):
        result, root, events = self.run_deploy(fail_ready=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ready', events)
        self.assertEqual((root / 'frontend/dist/index.html').read_text(), 'old-index')
        self.assertEqual(list((root / 'frontend').glob('.deploy-build.*')), [])


if __name__ == '__main__':
    unittest.main()
