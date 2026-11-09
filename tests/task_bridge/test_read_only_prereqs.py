"""Offline contract for the exact standalone #41 root-terminal inventory bytes."""
import ast
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'ops/bridge_one_shot/read_only_prereqs.sh'
GUIDE = ROOT / 'ops/bridge_one_shot/READ_ONLY_PREREQUISITES.md'


def source_and_module():
    shell = SCRIPT.read_text()
    match = re.search(r"<<'PY'\n(.*?)\nPY\n\)\n", shell, re.S)
    assert match
    code = match.group(1)
    namespace = {'__name__': 'offline_inventory'}
    exec(compile(ast.parse(code), str(SCRIPT), 'exec'), namespace)
    return shell, namespace


def test_exact_operator_fence_and_syntax():
    shell, _ = source_and_module()
    assert GUIDE.read_text().count('```bash\n') == 1
    assert GUIDE.read_text().split('```bash\n', 1)[1].split('\n```', 1)[0] + '\n' == shell
    assert subprocess.run(['bash', '-n'], input=shell, text=True, capture_output=True).returncode == 0
    assert '/usr/bin/python3 -I -B -' in shell
    assert 'BASH_ENV ENV PYTHONPATH PYTHONHOME' in shell
    assert 'STAGED ONLY' not in shell


def test_absent_candidates_are_normal_missing_not_go():
    _, module = source_and_module()
    report, missing = module['inventory']({}, run=lambda argv, **kw: b'')
    assert report['source'] == ('MISSING', 'NOT_CONFIGURED: protected bare store path')
    assert report['source_objects'][0] == 'MISSING'
    assert report['signer_key'][0] == 'MISSING'
    assert report['image_internal_isolation'][0] == 'UNPROVEN'
    assert report['manager_exclusive_invocation'][0] == 'UNPROVEN'
    assert report['persistent_worker'][0] == 'UNPROVEN'
    assert 'source' in missing
    assert all(value[0] in ('PRESENT', 'MISSING', 'UNPROVEN') for value in report.values())


def test_untrusted_and_symlinked_candidates_fail_closed():
    _, module = source_and_module()
    trusted = module['trusted']
    assert not trusted('/tmp', private=True)
    assert not trusted('/proc/self', private=True)  # symlink, never resolved
    assert not trusted('/root/../root', private=True)
    assert not trusted('relative')
    def no_git(argv, **kw):
        assert argv[:2] == ['docker', 'ps']  # no Git read on a symlinked source
        return b''
    report, _ = module['inventory']({'source':'/proc/self'}, run=no_git)
    assert report['source'][0] == 'MISSING'


def test_exact_git_objects_and_image_identity_are_only_metadata(monkeypatch):
    _, module = source_and_module()
    original = module['trusted']
    module['trusted'] = lambda path, **kw: True if path == '/protected/bare' else original(path, **kw)
    pins = {module[x] for x in ('MERGE', 'BOOTSTRAP', 'ADAPTER', 'RUNNER')}
    cid = 'a' * 64
    image = 'sha256:' + 'b' * 64
    seen = []
    def fake(argv, **kwargs):
        seen.append(argv)
        if argv[:2] == ['git', '--git-dir=/protected/bare']:
            if argv[-2:] == ['rev-parse', '--is-bare-repository']:
                return b'true\n'
            if argv[2:4] == ['cat-file', '-t'] and argv[-1] in pins:
                return b'commit\n'
            if argv[2:4] == ['merge-base', '--is-ancestor']:
                return b''
            return b'blob\n'
        if argv[:2] == ['docker', 'ps']:
            return (cid + '\n').encode()
        if argv[:3] == ['docker', 'container', 'inspect']:
            return (image + '|1001:1001|[{"Type":"bind","Source":"/other","Destination":"/state"}]|').encode()
        if argv[:3] == ['docker', 'image', 'inspect']:
            return (image + '\n').encode()
        raise AssertionError(argv)
    report, _ = module['inventory']({'source':'/protected/bare'}, run=fake)
    assert report['source_objects'][0] == 'PRESENT'
    assert report['image'][0] == 'PRESENT'
    assert report['container_mounts'][0] == 'UNPROVEN'
    assert report['dependencies'][0] == 'UNPROVEN'
    assert sum(x[2:4] == ['merge-base', '--is-ancestor'] for x in seen) == 3
    def mismatch(argv, **kw):
        if argv[:3] == ['docker', 'image', 'inspect']:
            return b'sha256:wrong\n'
        return fake(argv, **kw)
    report, _ = module['inventory']({'source':'/protected/bare'}, run=mismatch)
    assert report['image'][0] == 'MISSING'
    def git_fail(argv, **kw):
        if argv[:2] == ['git', '--git-dir=/protected/bare']:
            raise TimeoutError('private path must not appear in report')
        return fake(argv, **kw)
    report, _ = module['inventory']({'source':'/protected/bare'}, run=git_fail)
    assert report['source_objects'][0] == 'MISSING'
    assert '/protected/bare' not in str(report)
    def wrong_commit(argv, **kw):
        if argv[2:4] == ['cat-file', '-t'] and argv[-1] == module['ADAPTER']:
            return b'blob\n'
        return fake(argv, **kw)
    report, _ = module['inventory']({'source':'/protected/bare'}, run=wrong_commit)
    assert report['source_objects'][0] == 'MISSING'
    def leaked_mount(argv, **kw):
        if argv[:3] == ['docker', 'container', 'inspect']:
            return (image + '|1001:1001|[{"Type":"bind","Source":"/protected/bare/child","Destination":"/state"}]|').encode()
        return fake(argv, **kw)
    report, _ = module['inventory']({'source':'/protected/bare'}, run=leaked_mount)
    assert report['container_mounts'][0] == 'MISSING'


def test_forbidden_commands_and_secret_reads_are_excluded(monkeypatch):
    shell, module = source_and_module()
    assert "'{{json .Config.Env}}'" not in shell and 'auth.json' not in shell
    assert 'shell=True' not in shell and 'docker exec' not in shell
    def forbidden(*args, **kwargs):
        pytest.fail('a forbidden command reached subprocess')
    monkeypatch.setattr(module['subprocess'], 'Popen', forbidden)
    for argv in (['docker', 'exec', 'worker', 'env'],
                 ['git', '--git-dir=/protected/bare', 'show', 'HEAD:secret'],
                 ['docker', 'container', 'inspect', 'worker']):
        with pytest.raises(ValueError, match='allowlist'):
            module['bounded'](argv)
    class Reached(Exception):
        pass
    monkeypatch.setattr(module['subprocess'], 'Popen', lambda *a, **k: (_ for _ in ()).throw(Reached()))
    cid, image = 'a'*64, 'sha256:'+'b'*64
    allowed = [
        ['docker','ps','-aq','--no-trunc','--filter',module['LABEL'],'--format','{{.ID}}'],
        ['docker','container','inspect','--format','{{.Image}}|{{.Config.User}}|{{json .Mounts}}|',cid],
        ['docker','image','inspect','--format','{{.Id}}',image],
        ['git','--git-dir=/protected/bare','merge-base','--is-ancestor',module['RUNNER'],module['ADAPTER']],
    ]
    for argv in allowed:
        with pytest.raises(Reached):
            module['bounded'](argv)


def test_subprocess_output_and_deadline_are_bounded(monkeypatch):
    _, module = source_and_module()
    class FakeChild:
        def __init__(self, readable):
            self.stdout = os.fdopen(readable, 'rb', buffering=0)
            self.pid = 76543
        def poll(self):
            return None
        def wait(self, timeout=None):
            return 0
    writers = []
    def huge(*args, **kwargs):
        readable, writable = os.pipe()
        writers.append(writable)
        os.write(writable, b'x' * 4097)
        return FakeChild(readable)
    monkeypatch.setattr(module['subprocess'], 'Popen', huge)
    monkeypatch.setattr(module['os'], 'killpg', lambda *a: None)
    argv = ['git', '--git-dir=/protected/bare', 'rev-parse', '--is-bare-repository']
    with pytest.raises(ValueError, match='output bound'):
        module['bounded'](argv)
    for fd in writers: os.close(fd)
    def silent(*args, **kwargs):
        readable, writable = os.pipe()
        writers.append(writable)
        return FakeChild(readable)
    monkeypatch.setattr(module['subprocess'], 'Popen', silent)
    with pytest.raises(TimeoutError, match='timeout'):
        module['bounded'](argv, seconds=.01)
    os.close(writers[-1])
