"""Real owner process, fixture, nested-build and staging boundaries; no ARM."""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tests')]
import integrate_corsixth as assembly
from source_view import CANCEL_DOMAIN, independent_environment, binding, verify_staged_build, _live_group
from integration.common import IntegrationError
from support.pinned_upstream import original_sources

TOOL = ROOT/'tools/source_view.py'


@contextlib.contextmanager
def external_root(command, **kwargs):
    """Own only this test's explicit root session, including suite cancellation."""
    signals = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
    def cancelled(number, _frame):
        # unittest propagates KeyboardInterrupt, so cleanup runs and the suite
        # cannot catch SystemExit as a test error and continue executing tests.
        raise KeyboardInterrupt(f'external-root fixture cancelled by {number}')
    previous = {number: signal.signal(number, cancelled) for number in signals}
    owner = None
    groups = set()
    try:
        # Do not allow a signal exception between fork and saving its Popen owner.
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
        try:
            # The child inherits the temporary blocked mask. Restore its original
            # mask before exec, without running Python preexec_fn after fork.
            unblock = ('import os,signal,sys; '
                f'signal.pthread_sigmask(signal.SIG_SETMASK,{[int(n) for n in mask]!r}); '
                'os.execvpe(sys.argv[1],sys.argv[1:],os.environ)')
            owner = subprocess.Popen([sys.executable,'-c',unblock,*command],
                                     start_new_session=True, **kwargs)
            groups.add(owner.pid)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        yield owner, groups
    finally:
        for number in signals: signal.signal(number, signal.SIG_IGN)
        try:
            if owner is not None:
                if owner.poll() is None:
                    # Freeze this known root before enumerating its one worker.
                    # source_view creates that direct child's group with child
                    # PID as PGID; all production nesting remains in that group.
                    try: os.kill(owner.pid, signal.SIGSTOP)
                    except ProcessLookupError: pass
                    _, status = os.waitpid(owner.pid, os.WUNTRACED)
                    if os.WIFSTOPPED(status):
                        rows = subprocess.check_output(['ps','-axo','pid=,ppid='],text=True)
                        children = [int(pid) for pid,parent in (row.split() for row in rows.splitlines())
                                    if int(parent)==owner.pid]
                        groups.update(children)
                        # Also cover cancellation before the worker's setsid.
                        for pid in children:
                            try: os.kill(pid,signal.SIGKILL)
                            except ProcessLookupError: pass
                    else:
                        owner.returncode = os.waitstatus_to_exitcode(status)
                for group in groups:
                    if group <= 1 or group == os.getpgrp():
                        raise AssertionError('refuse unrelated fixture process group')
                    try: os.killpg(group,signal.SIGKILL)
                    except ProcessLookupError: pass
                owner.wait(timeout=3)
                deadline=time.monotonic()+3
                while any(_live_group(group) for group in groups):
                    if time.monotonic()>=deadline:
                        raise AssertionError('external-root fixture group still executing')
                    time.sleep(.01)
        finally:
            for number,handler in previous.items(): signal.signal(number,handler)


class SourceOwnerTests(unittest.TestCase):
    def test_cancel_entry_stops_worker_and_grandchild_and_invalidates_receipt(self):
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            with self.subTest(signal=sig.name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); receipt = root/'success.json'
                receipt.write_text('{"previous":true}')
                child = root/'child.py'
                child.write_text('import os,signal,sys,pathlib\n'
                    'p=pathlib.Path(sys.argv[1]); p.write_text(str(os.getpid()))\n'
                    'def stop(n,f):\n'
                    ' p.with_suffix(".stopped").write_text(str(n)); raise SystemExit(128+n)\n'
                    'for n in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT): signal.signal(n,stop)\n'
                    'print("READY",flush=True)\n'
                    'while True: signal.pause()\n')
                worker = root/'worker.sh'
                worker.write_text('''#!/bin/bash
trap 'rm -f "$1"' EXIT
trap 'exit 143' TERM
trap 'exit 129' HUP
trap 'exit 130' INT
"$2" "$3" "$4" &
wait $!
printf 'COMMITTED\n'
''')
                env = dict(independent_environment(), CTH3DS_SOURCE_OWNER_RECEIPT=str(receipt))
                # This test targets an external root entry, even when the suite
                # itself runs inside test_all's domain. Only the test deliberately
                # establishes this separate session; production nesting retains it.
                env.pop(CANCEL_DOMAIN, None)
                with external_root([sys.executable, str(TOOL), 'run', '--lock', str(root/'lock'),
                    '--', 'bash', str(worker), str(receipt), sys.executable, str(child), str(root/'grandchild')],
                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as (owner,groups):
                    self.assertEqual(owner.stdout.readline().strip(), 'READY')
                    groups.add(os.getpgid(int((root/'grandchild').read_text())))
                    owner.send_signal(sig)
                    out, err = owner.communicate(timeout=10)
                    self.assertEqual(owner.returncode, 128+sig, out+err)
                    self.assertNotIn('COMMITTED', out)
                    self.assertFalse(receipt.exists())
                    self.assertTrue((root/'grandchild.stopped').is_file())
                    pid = int((root/'grandchild').read_text())
                    state = subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True).stdout.strip()
                    self.assertTrue(not state or state.startswith('Z'), state)
                    # Cancellation has released the owner only after workers stop.
                    probe = subprocess.run([sys.executable,str(TOOL),'run','--lock',str(root/'lock'),
                        '--',sys.executable,'-c','print("next owner")'],env=independent_environment(),
                        capture_output=True,text=True,timeout=5)
                    self.assertEqual(probe.returncode,0,probe.stderr)

    def test_nested_isolation_keeps_one_cancel_domain_and_rejects_stale_metadata(self):
        for private_owner in (False, True):
            with self.subTest(private_owner=private_owner), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); ready = root/'ready'; receipt = root/'receipt'
                receipt.write_text('previous success')
                env = dict(independent_environment(), CTH3DS_SOURCE_OWNER_RECEIPT=str(receipt))
                env.pop(CANCEL_DOMAIN, None)  # external cancellation probe root
                payload = ('import os,signal,time,json,pathlib; '
                    'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                    f'pathlib.Path({str(ready)!r}).write_text(json.dumps(dict('
                    'pid=os.getpid(),parent=os.getppid(),group=os.getpgrp(),'
                    'domain=os.environ["CTH3DS_CANCEL_DOMAIN"]))); time.sleep(30)')
                command = [sys.executable, '-c', payload]
                if private_owner:
                    command = [sys.executable,str(TOOL),'run','--lock',str(root/'private-lock'),'--',*command]
                command = [sys.executable,str(TOOL),'run','--lock',str(root/'lock'),'--',
                           sys.executable,str(TOOL),'isolated','--',*command]
                with external_root(command,env=env,stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL) as (owner,groups):
                    deadline = time.monotonic()+5
                    while not ready.exists() and time.monotonic()<deadline: time.sleep(.02)
                    self.assertTrue(ready.exists())
                    info = json.loads(ready.read_text())
                    groups.add(info['group'])
                    self.assertEqual(info['group'],int(info['domain'].split(':')[1]))
                    os.kill(info['parent'],signal.SIGSTOP)
                    owner.send_signal(signal.SIGTERM)
                    time.sleep(.5)
                    os.kill(info['parent'],signal.SIGCONT)
                    self.assertEqual(owner.wait(timeout=8),143)
                    state = subprocess.run(['ps','-p',str(info['pid']),'-o','stat='],
                        capture_output=True,text=True).stdout.strip()
                    self.assertTrue(not state or state.startswith('Z'),state)
                    self.assertFalse(receipt.exists())
                    # A dead root marker must never silently open a new domain.
                    for marker in (info['domain'], 'bad', f'{os.getpid()}:999999999'):
                        denied = subprocess.run([sys.executable,str(TOOL),'isolated','--',
                            sys.executable,'-c','print("UNCONTROLLED")'],
                            env=dict(env,**{CANCEL_DOMAIN:marker}),capture_output=True,text=True,timeout=5)
                        self.assertEqual(denied.returncode,2,denied.stderr)
                        self.assertNotIn('UNCONTROLLED',denied.stdout)

    def test_cycle_build_switch_keeps_stable_owner_and_rejects_wrong_inode(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); external=root/'external'; external.mkdir()
            raw=original_sources(root/'raw')
            with contextlib.redirect_stdout(io.StringIO()):
                assembly.generate_private(raw,ROOT,external/'CorsixTH')
            lock=external/'.source-owner.lock'; build=root/'run-build'
            devkit=root/'devkit'; (devkit/'cmake').mkdir(parents=True)
            (devkit/'cmake/3DS.cmake').write_text('# control probe only')
            deps=root/'deps'; deps.mkdir(); (deps/'cth3ds-dependencies.json').write_text('{}')
            commands=root/'commands'; commands.mkdir(); trace=root/'trace'
            for name in ('arm-none-eabi-gcc','arm-none-eabi-g++','arm-none-eabi-ar'):
                item=commands/name; item.write_text('#!/bin/sh\nexit 88\n'); item.chmod(0o755)
            cmake=commands/'cmake'
            cmake.write_text('#!/bin/sh\nif [ "$1" = --version ]; then echo CONTROL; exit 0; fi\n'
                'echo "$*" >> "$TRACE"\ncase "$*" in *"--target clean"*) exit 47;; esac\nexit 0\n')
            cmake.chmod(0o755)
            env=dict(independent_environment(),CTH3DS_EXTERNAL_DIR=str(external),
                CTH3DS_BUILD_DIR=str(root/'default-build'),CTH3DS_DEPS_PREFIX=str(deps),
                CTH3DS_BUILD_MANIFEST=str(root/'receipt'),CTH3DS_BUILD_EVIDENCE_DIR=str(root/'evidence'),
                DEVKITPRO=str(devkit),TRACE=str(trace),PATH=str(commands)+os.pathsep+os.environ['PATH'])
            # Same common.sh owner domain as cycle; only child build output changes.
            script='source "$1"; CTH3DS_BUILD_DIR="$2" bash "$3" --skip-bootstrap'
            call=[sys.executable,str(TOOL),'run','--lock',str(lock),'--','bash','-c',script,
                  'cycle-contract',str(ROOT/'scripts/common.sh'),str(build),str(ROOT/'scripts/build_3ds.sh')]
            result=subprocess.run(call,env=env,text=True,capture_output=True,timeout=45)
            self.assertEqual(result.returncode,47,result.stdout+result.stderr)
            self.assertIn('--target clean',trace.read_text())
            self.assertNotIn('--target corsixth_3dsx',trace.read_text())
            # A real but unrelated inherited descriptor remains a rejection.
            wrong=root/'wrong-lock'; wrong.touch()
            nested=[sys.executable,str(TOOL),'run','--lock',str(lock),'--',
                    sys.executable,str(TOOL),'check-owner','--lock',str(wrong)]
            denied=subprocess.run(nested,env=env,capture_output=True,text=True,timeout=5)
            self.assertEqual(denied.returncode,2,denied.stderr)

    def test_production_parent_owner_isolates_package_and_owner_fixtures(self):
        ids=['test_package_sd_script.PackageSdScriptTests.test_loose_mode_is_diagnostic_and_excludes_user_save',
             'test_package_sd_script.PackageSdScriptTests.test_th3ds_candidate_is_complete_atomic_and_excludes_loose_originals',
             'test_generated_view.GeneratedViewTests.test_owner_serializes_real_processes_and_rejects_forged_fd']
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); lock=root/'lock'; marker=root/'lock-held'
            env=dict(independent_environment(),PYTHONPATH=str(ROOT/'tools')+os.pathsep+str(ROOT/'tests'),
                     PYTHONDONTWRITEBYTECODE='1')
            script='source "$1"; independent_tests "$2" -B -m unittest "${@:3}"; python3 "$CTH3DS_ROOT/tools/source_view.py" check-owner --lock "$CTH3DS_SOURCE_OWNER_LOCK"'
            result=subprocess.run([sys.executable,str(TOOL),'run','--lock',str(lock),'--','bash','-c',
                script,'fixture-parent',str(ROOT/'scripts/common.sh'),sys.executable,*ids],
                env=env,cwd=ROOT,text=True,capture_output=True,timeout=40)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('Ran 3 tests',result.stderr)
            # Direct fixture invocation under an owner also clears stale metadata
            # at the fixture boundary, even when subprocess closes inherited FDs.
            direct=subprocess.run([sys.executable,str(TOOL),'run','--lock',str(lock),'--',
                sys.executable,'-B','-m','unittest',ids[0]],env=env,cwd=ROOT,
                text=True,capture_output=True,timeout=20)
            self.assertEqual(direct.returncode,0,direct.stdout+direct.stderr)

    def test_prepare_same_build_accepts_and_mid_copy_rebuild_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); raw=original_sources(root/'raw'); view=root/'view'
            assembly.generate_private(raw,ROOT,view)
            binary=root/'binary'; manifest=root/'manifest'; staged=root/'staged'
            git=lambda ref:subprocess.check_output(['git','-C',str(ROOT),'rev-parse',ref],text=True).strip()
            def publish(data):
                binary.write_bytes(data)
                value=binding(view,ROOT,binary)
                manifest.write_text(json.dumps({'source_commit':git('HEAD'),'source_tree':git('HEAD^{tree}'),
                                                'generated_source':value}))
                return value
            a=publish(b'A'); staged.write_bytes(binary.read_bytes())
            self.assertEqual(verify_staged_build(a,view,ROOT,binary,manifest,staged),a)
            publish(b'B'); staged.write_bytes(binary.read_bytes())
            with self.assertRaises(IntegrationError): verify_staged_build(a,view,ROOT,binary,manifest,staged)
            publish(b'A'); staged.write_bytes(b'B')
            with self.assertRaises(IntegrationError): verify_staged_build(a,view,ROOT,binary,manifest,staged)


if __name__=='__main__': unittest.main()
