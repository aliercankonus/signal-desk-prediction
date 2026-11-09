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
    assert report['source'][0] == 'NOT_CONFIGURED'
    assert report['source_objects'][0] == 'UNPROVEN'
    assert report['signer_key'][0] == 'NOT_CONFIGURED'
    assert report['image_internal_isolation'][0] == 'UNPROVEN'
    assert report['manager_exclusive_invocation'][0] == 'UNPROVEN'
    assert report['persistent_worker'][0] == 'UNPROVEN'
    assert 'source' not in missing
    assert all(value[0] in ('PRESENT', 'MISSING', 'UNPROVEN', 'NOT_CONFIGURED') for value in report.values())


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


def offline_docker(monkeypatch, module, project_ids=(), image=None, mounts=None,
                   candidate_id=None, inspected_image=None, image_missing=False):
    """Exercise the real command allowlist and parser; fake only Popen."""
    cid = candidate_id or ('a' * 64)
    image = image or ('sha256:' + 'b' * 64)
    seen = []
    class Child:
        def __init__(self, payload):
            readable, writable = os.pipe()
            os.write(writable, payload)
            os.close(writable)
            self.stdout = os.fdopen(readable, 'rb', buffering=0)
            self.pid = 76543
        def poll(self):
            return 0
        def wait(self, timeout=None):
            return 0
    def fake_popen(argv, **kwargs):
        seen.append(argv)
        assert kwargs['stderr'] is subprocess.DEVNULL
        assert kwargs['env']['GIT_CONFIG_GLOBAL'] == '/dev/null'
        if argv[:2] == ['/usr/bin/docker', 'ps']:
            return Child(('\n'.join(project_ids) + ('\n' if project_ids else '')).encode())
        if argv[:3] == ['/usr/bin/docker', 'container', 'inspect']:
            assert argv[-1] in set(project_ids) | {cid}
            data = mounts if mounts is not None else [
                {'Type':'bind', 'Source':'/unrelated', 'Destination':'/state'}]
            return Child((image + '|1001:1001|' + __import__('json').dumps(data) + '|').encode())
        if argv[:3] == ['/usr/bin/docker', 'image', 'inspect']:
            if image_missing:
                raise LookupError('image not found')
            return Child(((inspected_image if inspected_image is not None else image) + '\n').encode())
        raise AssertionError('unexpected or effectful command: ' + str(argv[:3]))
    monkeypatch.setattr(module['subprocess'], 'Popen', fake_popen)
    return seen, cid, image


def test_absent_project_with_available_explicit_candidate_image(monkeypatch):
    _, module = source_and_module()
    image = 'sha256:' + 'b' * 64
    seen, _, _ = offline_docker(monkeypatch, module)
    report, missing = module['inventory']({'image':image}, run=module['bounded'])
    assert report['image'][0] == 'PRESENT'
    assert report['container_mounts'][0] == 'UNPROVEN'
    assert 'image' not in missing
    assert any(row[:3] == ['/usr/bin/docker','image','inspect'] for row in seen)


def test_normal_two_container_project_inspects_both_without_explicit_image(monkeypatch):
    _, module = source_and_module()
    ids = ('a'*64, 'c'*64)
    seen, _, _ = offline_docker(monkeypatch, module, project_ids=ids)
    report, missing = module['inventory']({}, run=module['bounded'])
    assert report['image'][0] == 'PRESENT'
    assert report['container_mounts'][0] == 'UNPROVEN'  # not global isolation
    assert 'image' not in missing
    assert {row[-1] for row in seen if row[:3] == ['/usr/bin/docker','container','inspect']} == set(ids)


def test_optional_container_identity_without_project_is_only_candidate(monkeypatch):
    _, module = source_and_module()
    seen, cid, _ = offline_docker(monkeypatch, module)
    report, _ = module['inventory']({'container':cid}, run=module['bounded'])
    assert report['image'][0] == 'PRESENT'
    assert report['container_mounts'][0] == 'UNPROVEN'
    assert any(row[-1] == cid for row in seen)


def test_unknown_image_candidate_is_unproven_but_bad_observed_image_missing(monkeypatch):
    _, module = source_and_module()
    offline_docker(monkeypatch, module)
    report, _ = module['inventory']({}, run=module['bounded'])
    assert report['image'][0] == 'UNPROVEN'
    offline_docker(monkeypatch, module, inspected_image='sha256:' + 'f'*64)
    report, _ = module['inventory']({'image':'sha256:' + 'b'*64}, run=module['bounded'])
    assert report['image'][0] == 'MISSING'
    offline_docker(monkeypatch, module, image_missing=True)
    report, _ = module['inventory']({'image':'sha256:' + 'b'*64}, run=module['bounded'])
    assert report['image'][0] == 'MISSING'


def test_unavailable_explicit_container_does_not_imply_absent_image(monkeypatch):
    _, module = source_and_module()
    cid = 'd'*64
    def fake_popen(argv, **kwargs):
        if argv[:3] == ['/usr/bin/docker', 'container', 'inspect']:
            raise LookupError('candidate not found')
        return original(argv, **kwargs)
    offline_docker(monkeypatch, module)
    original = module['subprocess'].Popen
    monkeypatch.setattr(module['subprocess'], 'Popen', fake_popen)
    report, _ = module['inventory']({'container':cid}, run=module['bounded'])
    assert report['candidate_container'][0] == 'UNPROVEN'
    assert report['container_mounts'][0] == 'UNPROVEN'
    assert report['image'][0] == 'UNPROVEN'


def test_one_uninspected_project_container_never_proves_exclusion(monkeypatch):
    _, module = source_and_module()
    ids = ('a'*64, 'c'*64)
    offline_docker(monkeypatch, module, project_ids=ids)
    original = module['subprocess'].Popen
    def partial(argv, **kwargs):
        if argv[:3] == ['/usr/bin/docker', 'container', 'inspect'] and argv[-1] == ids[1]:
            raise LookupError('second project container not inspected')
        return original(argv, **kwargs)
    monkeypatch.setattr(module['subprocess'], 'Popen', partial)
    report, _ = module['inventory']({}, run=module['bounded'])
    assert report['container_mounts'][0] == 'UNPROVEN'
    assert report['project_containers'][0] == 'PRESENT'


@pytest.mark.parametrize(('mount_source', 'expected'), [
    ('/protected/bare', 'MISSING'),
    ('/protected/bare/child', 'MISSING'),
    ('/protected', 'MISSING'),
    ('/', 'MISSING'),
    ('/protected/bare-sibling', 'UNPROVEN'),
    ('/protected/../protected/bare', 'MISSING'),
    ('relative/mount', 'MISSING'),
])
def test_bind_mount_overlap_both_ancestry_directions_and_malformed_metadata(
        monkeypatch, mount_source, expected):
    _, module = source_and_module()
    original = module['trusted']
    module['trusted'] = lambda path, **kw: True if path == '/protected/bare' else original(path, **kw)
    mounts = [{'Type':'bind','Source':mount_source,'Destination':'/state'}]
    offline_docker(monkeypatch, module, project_ids=('a'*64,), mounts=mounts)
    report, _ = module['inventory']({'source':'/protected/bare'}, run=module['bounded'])
    assert report['container_mounts'][0] == expected


def test_optional_root_signer_file_exposed_by_parent_bind_is_rejected(monkeypatch):
    _, module = source_and_module()
    mounts = [{'Type':'bind','Source':'/root-only','Destination':'/private'}]
    offline_docker(monkeypatch, module, project_ids=('a'*64,), mounts=mounts)
    report, _ = module['inventory']({'signer_key':'/root-only/key.pem'}, run=module['bounded'])
    assert report['container_mounts'][0] == 'MISSING'


def test_volume_mount_source_exposing_protected_parent_is_not_exempt(monkeypatch):
    _, module = source_and_module()
    original = module['trusted']
    module['trusted'] = lambda path, **kw: True if path == '/protected/bare' else original(path, **kw)
    mounts = [{'Type':'volume','Source':'/protected','Destination':'/state'}]
    offline_docker(monkeypatch, module, project_ids=('a'*64,), mounts=mounts)
    report, _ = module['inventory']({'source':'/protected/bare'}, run=module['bounded'])
    assert report['container_mounts'][0] == 'MISSING'


def test_normal_tmpfs_has_no_host_source_to_compare(monkeypatch):
    _, module = source_and_module()
    mounts = [{'Type':'tmpfs','Source':'','Destination':'/tmp'},
              {'Type':'bind','Source':'/unrelated','Destination':'/state'}]
    offline_docker(monkeypatch, module, project_ids=('a'*64,'c'*64), mounts=mounts)
    report, _ = module['inventory']({}, run=module['bounded'])
    assert report['container_mounts'][0] == 'UNPROVEN'
    assert report['image'][0] == 'PRESENT'


@pytest.mark.parametrize('raw', [
    '[]', '{"extra":"value"}', '{"source":true}',
    '{"source":"/one","source":"/two"}', '{"source":"relative"}',
    '{"source":"/"}', '{"image":"latest"}', '{"container":"worker"}',
    '{"source":"/private/../other"}', 'x' * 8193,
])
def test_private_candidate_payload_rejected_before_any_reads(monkeypatch, capsys, raw):
    _, module = source_and_module()
    monkeypatch.setenv('SD_INVENTORY_CANDIDATES', raw)
    monkeypatch.setattr(module['os'], 'geteuid', lambda: 0)
    module['ask'] = lambda *a: pytest.fail('invalid noninteractive payload must not prompt')
    module['inventory'] = lambda *a: pytest.fail('invalid payload must not reach inventory')
    module['main']()
    output = capsys.readouterr().out
    assert 'OVERALL: NO-GO' in output
    assert '/private' not in output and raw not in output


def test_empty_private_payload_never_prompts_or_tries_container_venv(monkeypatch, capsys):
    _, module = source_and_module()
    monkeypatch.setenv('SD_INVENTORY_CANDIDATES', '{}')
    monkeypatch.setattr(module['os'], 'geteuid', lambda: 0)
    module['ask'] = lambda *a: pytest.fail('private input must not prompt')
    # Real inventory/validator, fake only Docker subprocess I/O.
    seen, _, _ = offline_docker(monkeypatch, module)
    original = module['trusted']
    def no_fallback(value, **kw):
        assert not value.startswith('/opt/data')
        return original(value, **kw)
    module['trusted'] = no_fallback
    module['main']()
    output = capsys.readouterr().out
    assert 'INPUT_MODE: PRIVATE_CANDIDATES' in output
    assert 'VENV: NOT_CONFIGURED' in output
    assert 'SOURCE: NOT_CONFIGURED' in output
    assert 'OVERALL: NO-GO' in output
    assert all(row[:2] == ['/usr/bin/docker', 'ps'] for row in seen)


def test_private_candidates_use_real_validator_without_echo_or_secret_read(monkeypatch, capsys):
    _, module = source_and_module()
    seen, cid, image = offline_docker(monkeypatch, module)
    import json
    monkeypatch.setenv('SD_INVENTORY_CANDIDATES', json.dumps({
        'source':'/nonexistent-private-candidate', 'container':cid, 'image':image}))
    monkeypatch.setattr(module['os'], 'geteuid', lambda: 0)
    module['ask'] = lambda *a: pytest.fail('candidate mode must not prompt')
    module['main']()
    output = capsys.readouterr().out
    assert 'SOURCE: MISSING' in output
    assert 'IMAGE: PRESENT' in output
    assert '/nonexistent-private-candidate' not in output
    assert cid not in output and image not in output
    assert 'OVERALL: NO-GO' in output
    assert any(row[-1] == cid for row in seen)
    assert all('SD_INVENTORY_CANDIDATES' not in module['ENV'] for _ in seen)


def test_host_venv_symlink_interpreter_is_unproven_without_execution(monkeypatch, tmp_path):
    _, module = source_and_module()
    host = tmp_path / 'host-venv'
    (host / 'bin').mkdir(parents=True)
    (host / 'pyvenv.cfg').write_text('version = fixture\n')
    (host / 'bin/python').symlink_to('/unavailable-container-interpreter')
    original = module['trusted']
    module['trusted'] = lambda value, **kw: True if value == str(host) else original(value, **kw)
    seen, _, _ = offline_docker(monkeypatch, module)
    report, missing = module['inventory']({'venv':str(host)}, run=module['bounded'])
    assert report['venv'][0] == 'PRESENT'
    assert report['interpreter'][0] == 'UNPROVEN'
    assert 'interpreter' not in missing
    assert all(row[:2] == ['/usr/bin/docker', 'ps'] for row in seen)
