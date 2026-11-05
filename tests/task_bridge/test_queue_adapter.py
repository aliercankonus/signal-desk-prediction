"""Inert authorized-queue tests; no real Bridge, network, or Hermes child."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from signal_desk.task_bridge.bridge import Policy

WORKER = Path(__file__).resolve().parents[2] / 'autonomous-development'
sys.path.insert(0, str(WORKER))
from queue_store import TaskStore


def test_selected_worker_queue_has_no_legacy_agent_launcher():
    import queue_store
    assert not hasattr(queue_store, 'execute_task')
    assert not hasattr(queue_store, 'run_queue')


def test_queue_rejects_symlink_lock_before_dispatch(tmp_path):
    import pytest
    from bridge_queue import BridgeQueue
    store = TaskStore(tmp_path / 'queue')
    external = tmp_path / 'other.lock'
    external.write_text('untouched')
    external.chmod(0o600)
    (store.root / '.runner.lock').symlink_to(external)
    with pytest.raises(OSError):
        BridgeQueue(store).dispatch_one(lambda *_: (_ for _ in ()).throw(AssertionError('called')))
    assert external.read_text() == 'untouched'


def test_queue_rejects_public_existing_root(tmp_path):
    import pytest
    root = tmp_path / 'queue'
    root.mkdir(mode=0o755)
    with pytest.raises(PermissionError):
        TaskStore(root)


def test_new_queue_root_is_synced_to_parent(tmp_path, monkeypatch):
    import queue_store
    parent_identity = (tmp_path.stat().st_dev, tmp_path.stat().st_ino)
    original = queue_store.os.fsync
    synced = []

    def tracked(fd):
        info = queue_store.os.fstat(fd)
        if (info.st_dev, info.st_ino) == parent_identity:
            synced.append(True)
        return original(fd)

    monkeypatch.setattr(queue_store.os, 'fsync', tracked)
    store = TaskStore(tmp_path / 'queue')
    assert store.root.is_dir() and synced


def test_queue_rechecks_parent_privacy_before_claim(tmp_path):
    import pytest
    from bridge_queue import BridgeQueue
    store = TaskStore(tmp_path / 'queue')
    old_mode = tmp_path.stat().st_mode & 0o777
    tmp_path.chmod(0o777)
    try:
        with pytest.raises(PermissionError):
            BridgeQueue(store).dispatch_one(lambda *_: (_ for _ in ()).throw(AssertionError('called')))
    finally:
        tmp_path.chmod(old_mode)


def test_queue_rejects_a_parent_owned_by_another_unprivileged_uid(tmp_path, monkeypatch):
    import os
    import pytest
    import queue_store
    foreign = tmp_path / 'foreign'
    foreign.mkdir(mode=0o700)
    original = queue_store.os.lstat

    def changed_owner(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if os.fspath(path) == str(foreign):
            fields = list(info)
            fields[4] = os.geteuid() + 1
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(queue_store.os, 'lstat', changed_owner)
    with pytest.raises(PermissionError):
        TaskStore(foreign / 'queue')


def test_adapter_refuses_legacy_worker_queue_root(tmp_path, monkeypatch):
    import pytest
    import queue_store
    old_root = tmp_path / 'legacy'
    monkeypatch.setattr(queue_store, 'LEGACY_ROOT', old_root)
    with pytest.raises(ValueError, match='legacy'):
        TaskStore(old_root)
    assert not old_root.exists()


def test_adapter_refuses_queue_inside_runner_checkout(tmp_path):
    import pytest
    from bridge_queue import BridgeQueue
    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(source / 'queue')
    with pytest.raises(ValueError, match='outside'):
        BridgeQueue(store).enqueue(source, authorization, context, runner_commit=head)


def test_enqueue_refuses_queue_root_replaced_by_symlink(tmp_path):
    import pytest
    from bridge_queue import BridgeQueue
    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    external = tmp_path / 'external'
    external.mkdir(mode=0o700)
    store.root.rename(tmp_path / 'old-queue')
    store.root.symlink_to(external, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        BridgeQueue(store).enqueue(source, authorization, context, runner_commit=head)
    assert list(external.iterdir()) == []


def test_queue_rejects_ancestor_replacement_after_store_construction(tmp_path):
    import pytest
    from bridge_queue import BridgeQueue
    original = tmp_path / 'parent'
    private = original / 'private'
    private.mkdir(parents=True, mode=0o700)
    store = TaskStore(private / 'queue')
    alternate = tmp_path / 'alternate'
    (alternate / 'private').mkdir(parents=True, mode=0o700)
    (alternate / 'private' / 'queue').mkdir(mode=0o700)
    original.rename(tmp_path / 'old-parent')
    original.symlink_to(alternate, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        BridgeQueue(store).dispatch_one(lambda *_: (_ for _ in ()).throw(AssertionError('called')))
    assert list((alternate / 'private' / 'queue').iterdir()) == []


def test_lock_open_is_pinned_to_original_queue_directory(tmp_path, monkeypatch):
    import pytest
    store = TaskStore(tmp_path / 'queue')
    original_check = store._check

    def replace_after_check():
        original_check()
        store.root.rename(tmp_path / 'old-queue')
        store.root.mkdir(mode=0o700)

    monkeypatch.setattr(store, '_check', replace_after_check)
    with pytest.raises((OSError, ValueError)):
        with store.lock():
            pass
    assert not (store.root / '.runner.lock').exists()


def test_state_write_is_pinned_to_original_queue_directory(tmp_path, monkeypatch):
    import pytest
    store = TaskStore(tmp_path / 'queue')
    task_id = 'c' * 32
    store.create_entry_directory(task_id)
    original_check = store._check
    replaced = False

    def replace_after_check():
        nonlocal replaced
        original_check()
        if not replaced:
            replaced = True
            store.root.rename(tmp_path / 'old-queue')
            store.root.mkdir(mode=0o700)
            (store.root / task_id).mkdir(mode=0o700)

    monkeypatch.setattr(store, '_check', replace_after_check)
    with pytest.raises((OSError, ValueError)):
        store.save({'id': task_id, 'kind': 'bridge', 'status': 'queued', 'created_ns': 1})
    assert not (store.root / task_id / 'state.json').exists()


def reviewed_fixture(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    subprocess.run(['git', '-C', str(source), 'init', '-q', '-b', 'main'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture',
                    '-c', 'user.email=fixture@example.invalid', 'commit', '-q',
                    '--allow-empty', '-m', 'fixture'], check=True)
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    authorization = private / 'authorization.json'
    authorization.write_text(json.dumps({'repo': 'aliercankonus/signal-desk-prediction',
                                         'issue': 101, 'body_digest': hashlib.sha256(b'fixture issue').hexdigest(),
                                         'base': head, 'branch': 'review-task-101'}))
    authorization.chmod(0o600)
    context = private / 'context.json'
    context.write_text(json.dumps({'test_python': '/private/venvs/reviewed/bin/python',
                                   'requirements_sha256': 'a' * 64, 'runner_commit': head,
                                   'python_version': '3.14.9', 'pytest_version': '8.3.3'}))
    context.chmod(0o600)
    return source, authorization, context, head


def test_bridge_entry_is_only_visible_to_bridge_queue(tmp_path):
    store = TaskStore(tmp_path / 'queue')
    task_id = 'a' * 32
    (store.root / task_id).mkdir(mode=0o700)
    store.save({'id': task_id, 'kind': 'bridge', 'status': 'queued',
                'created_ns': 1, 'repo': str(tmp_path)})
    assert store.all_tasks()[0]['id'] == task_id


def test_enqueue_pins_reviewed_authorization_context_and_run_mapping(tmp_path):
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    entry = BridgeQueue(store).enqueue(source, authorization, context, runner_commit=head)
    saved = store.load(entry['id'])
    assert saved['kind'] == 'bridge' and saved['status'] == 'queued'
    assert saved['runner_commit'] == head
    assert saved['authorization_identity'] == Policy(**json.loads(authorization.read_text())).identity
    assert saved['bridge_state'] == str(store.root / saved['id'] / 'bridge')
    assert saved['bridge_run_id'] and saved['invocations'] == 0
    assert saved['ci'] is None and saved['pr_url'] is None
    assert (store.root / saved['id'] / 'state.json').stat().st_mode & 0o777 == 0o600


def test_bridge_accepts_preallocated_run_identity(tmp_path):
    from signal_desk.task_bridge.bridge import Bridge

    policy = Policy(repo='aliercankonus/signal-desk-prediction', issue=101,
                    body_digest='a' * 64, base='b' * 40, branch='review-task-101')
    bridge = Bridge(tmp_path / 'bridge', policy, object(), object(), run_id='c' * 32)
    assert bridge.run_id == 'c' * 32


def test_dispatch_calls_one_bridge_after_persisting_mapping_and_receipt(tmp_path):
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    queue = BridgeQueue(store)
    entry = queue.enqueue(source, authorization, context, runner_commit=head)
    calls = []
    pr_url = 'https://github.com/aliercankonus/signal-desk-prediction/pull/99'
    receipt = {'stage': 'verified', 'expected_head': 'b' * 40,
               'number': 99, 'url': pr_url}

    class FakeBridge:
        def once(self):
            calls.append('once')
            during = store.load(entry['id'])
            assert during['status'] == 'running' and during['invocations'] == 1
            assert during['bridge_state'] == str(store.root / entry['id'] / 'bridge')
            assert during['bridge_run_id'] == entry['bridge_run_id']
            return {'status': 'review-ready', 'run_id': entry['bridge_run_id'],
                    'base': head, 'head': 'b' * 40, 'pr_url': pr_url, 'ci': 'pending'}

        def _pr_creation(self):
            return receipt

    def factory(item, policy):
        assert item['authorization_identity'] == policy.identity
        return FakeBridge()

    result = queue.dispatch_one(factory)
    assert calls == ['once']
    assert result['status'] == 'review-ready' and result['ci'] == 'pending'
    saved = store.load(entry['id'])
    assert saved['bridge_result']['head'] == 'b' * 40
    assert saved['receipt'] == receipt and saved['checkpoint'] is None
    assert queue.dispatch_one(factory)['status'] == 'review-ready'
    assert calls == ['once']


def test_authorization_change_during_fake_bridge_blocks_ready_receipt(tmp_path):
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    queue = BridgeQueue(store)
    entry = queue.enqueue(source, authorization, context, runner_commit=head)
    url = 'https://github.com/aliercankonus/signal-desk-prediction/pull/99'

    class FakeBridge:
        def once(self):
            changed = json.loads(authorization.read_text())
            changed['body_digest'] = 'f' * 64
            authorization.write_text(json.dumps(changed))
            return {'status': 'review-ready', 'run_id': entry['bridge_run_id'],
                    'base': head, 'head': 'b' * 40, 'pr_url': url, 'ci': 'success'}

        def _pr_creation(self):
            return {'stage': 'verified', 'expected_head': 'b' * 40,
                    'number': 99, 'url': url}

    assert queue.dispatch_one(lambda _item, _policy: FakeBridge())['status'] == 'blocked'
    assert store.load(entry['id'])['status'] == 'blocked'


def test_authorization_file_must_not_live_in_queue_state(tmp_path):
    import pytest
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    unsafe_auth = store.root / 'authorization.json'
    unsafe_auth.write_bytes(authorization.read_bytes())
    unsafe_auth.chmod(0o600)
    with pytest.raises(ValueError, match='outside'):
        BridgeQueue(store).enqueue(source, unsafe_auth, context, runner_commit=head)
    assert not list(store.root.glob('*/state.json'))


def test_changed_authorization_before_dispatch_blocks_without_bridge_call(tmp_path):
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    queue = BridgeQueue(store)
    entry = queue.enqueue(source, authorization, context, runner_commit=head)
    record = json.loads(authorization.read_text())
    record['body_digest'] = 'f' * 64
    authorization.write_text(json.dumps(record))
    result = queue.dispatch_one(lambda *_: (_ for _ in ()).throw(AssertionError('factory called')))
    assert result['status'] == 'blocked'
    assert store.load(entry['id'])['invocations'] == 0
    assert store.load(entry['id'])['failure_code'] == 'preflight'


def test_queue_local_authority_and_context_cannot_be_replayed_at_dispatch(tmp_path):
    from bridge_queue import BridgeQueue
    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    queue = BridgeQueue(store)
    entry = queue.enqueue(source, authorization, context, runner_commit=head)
    folder = store.root / entry['id']
    local_auth = folder / 'authorization.json'
    local_context = folder / 'context.json'
    local_auth.write_bytes(authorization.read_bytes())
    local_context.write_bytes(context.read_bytes())
    local_auth.chmod(0o600)
    local_context.chmod(0o600)
    entry['authorization_path'] = str(local_auth)
    entry['context_path'] = str(local_context)
    store.save(entry)
    called = []
    assert queue.dispatch_one(lambda *_: called.append(True))['status'] == 'blocked'
    assert called == [] and store.load(entry['id'])['invocations'] == 0


def test_changed_private_context_before_dispatch_blocks(tmp_path):
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    queue = BridgeQueue(store)
    entry = queue.enqueue(source, authorization, context, runner_commit=head)
    record = json.loads(context.read_text())
    record['pytest_version'] = '9.9.9'
    context.write_text(json.dumps(record))
    assert queue.dispatch_one(lambda *_: (_ for _ in ()).throw(AssertionError('factory called')))['status'] == 'blocked'
    assert store.load(entry['id'])['invocations'] == 0


def test_changed_runner_head_before_dispatch_blocks(tmp_path):
    from bridge_queue import BridgeQueue
    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    queue = BridgeQueue(store)
    entry = queue.enqueue(source, authorization, context, runner_commit=head)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture',
                    '-c', 'user.email=fixture@example.invalid', 'commit', '-q',
                    '--allow-empty', '-m', 'changed'], check=True)
    assert queue.dispatch_one(lambda *_: (_ for _ in ()).throw(AssertionError('factory called')))['status'] == 'blocked'
    assert store.load(entry['id'])['invocations'] == 0


def test_dirty_runner_at_same_head_blocks_before_bridge_factory(tmp_path):
    from bridge_queue import BridgeQueue
    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    queue = BridgeQueue(store)
    entry = queue.enqueue(source, authorization, context, runner_commit=head)
    (source / 'unreviewed.py').write_text('print("unreviewed")\n')
    called = []
    assert queue.dispatch_one(lambda *_: called.append(True))['status'] == 'blocked'
    assert called == [] and store.load(entry['id'])['invocations'] == 0


def test_dirty_runner_cannot_be_enqueued(tmp_path):
    import pytest
    from bridge_queue import BridgeQueue
    source, authorization, context, head = reviewed_fixture(tmp_path)
    (source / 'unreviewed.py').write_text('print("unreviewed")\n')
    store = TaskStore(tmp_path / 'queue')
    with pytest.raises(ValueError, match='clean'):
        BridgeQueue(store).enqueue(source, authorization, context, runner_commit=head)
    assert store.all_tasks() == []


def test_modified_tracked_runner_at_same_head_cannot_be_enqueued(tmp_path):
    import pytest
    from bridge_queue import BridgeQueue
    source, authorization, context, _ = reviewed_fixture(tmp_path)
    tracked = source / 'tracked.py'
    tracked.write_text('print("reviewed")\n')
    subprocess.run(['git', '-C', str(source), 'add', 'tracked.py'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture',
                    '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '-m', 'reviewed'], check=True)
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    details = json.loads(context.read_text())
    details['runner_commit'] = head
    context.write_text(json.dumps(details))
    tracked.write_text('print("unreviewed")\n')
    store = TaskStore(tmp_path / 'queue')
    with pytest.raises(ValueError, match='clean'):
        BridgeQueue(store).enqueue(source, authorization, context, runner_commit=head)
    assert store.all_tasks() == []


def test_production_factory_rejects_imported_bridge_from_other_checkout(tmp_path):
    import pytest
    from bridge_queue import BridgeQueue
    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    entry = BridgeQueue(store).enqueue(source, authorization, context, runner_commit=head)
    with pytest.raises(ValueError, match='runtime'):
        BridgeQueue.production_bridge(entry, object())


def test_production_factory_rejects_existing_bytecode_cache(tmp_path, monkeypatch):
    import pytest
    import bridge_queue
    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    entry = bridge_queue.BridgeQueue(store).enqueue(source, authorization, context, runner_commit=head)
    cache = tmp_path / 'ignored.pyc'
    cache.write_bytes(b'inert fixture, never imported')
    monkeypatch.setattr(bridge_queue, '__cached__', str(cache))
    with pytest.raises(ValueError, match='cache'):
        bridge_queue.BridgeQueue.production_bridge(entry, object())


def test_crash_after_durable_running_state_blocks_restart_without_redispatch(tmp_path):
    import pytest
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    queue = BridgeQueue(store)
    entry = queue.enqueue(source, authorization, context, runner_commit=head)
    calls = []

    class CrashingBridge:
        def once(self):
            calls.append('once')
            assert store.load(entry['id'])['status'] == 'running'
            raise SystemExit(91)

    with pytest.raises(SystemExit):
        queue.dispatch_one(lambda *_: CrashingBridge())
    saved = store.load(entry['id'])
    assert saved['status'] == 'running' and saved['invocations'] == 1
    restarted = BridgeQueue(TaskStore(store.root))
    assert restarted.dispatch_one(lambda *_: (_ for _ in ()).throw(AssertionError('redispatched')))['status'] == 'blocked'
    assert calls == ['once']


def test_quota_shaped_bridge_block_and_acknowledgment_never_redispatch(tmp_path):
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    queue = BridgeQueue(store)
    entry = queue.enqueue(source, authorization, context, runner_commit=head)
    calls = []

    class QuotaBridge:
        def once(self):
            calls.append('once')
            return {'status': 'blocked', 'run_id': entry['bridge_run_id'],
                    'reason': 'HTTP 429 usage_limit_reached, private diagnostic only'}

    assert queue.dispatch_one(lambda *_: QuotaBridge())['status'] == 'blocked'
    assert store.load(entry['id'])['failure_code'] == 'bridge'
    assert 'usage_limit_reached' not in json.dumps(store.load(entry['id']))
    store.acknowledge_block(entry['id'])
    assert queue.dispatch_one(lambda *_: QuotaBridge())['status'] == 'blocked'
    assert calls == ['once'] and store.load(entry['id'])['invocations'] == 1


def test_mismatched_draft_receipt_cannot_be_review_ready(tmp_path):
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    queue = BridgeQueue(store)
    entry = queue.enqueue(source, authorization, context, runner_commit=head)
    url = 'https://github.com/aliercankonus/signal-desk-prediction/pull/99'

    class FakeBridge:
        def once(self):
            return {'status': 'review-ready', 'run_id': entry['bridge_run_id'],
                    'base': head, 'head': 'b' * 40, 'pr_url': url, 'ci': 'success'}

        def _pr_creation(self):
            return {'stage': 'intent', 'expected_head': 'b' * 40, 'number': None, 'url': None}

    assert queue.dispatch_one(lambda *_: FakeBridge())['status'] == 'blocked'
    saved = store.load(entry['id'])
    assert saved['status'] == 'blocked' and saved['failure_code'] == 'ambiguous'
    assert saved['ci'] is None and saved['pr_url'] is None


def test_concurrent_consumers_never_invoke_the_same_bridge_twice(tmp_path):
    import threading
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    entry = BridgeQueue(store).enqueue(source, authorization, context, runner_commit=head)
    entered, release = threading.Event(), threading.Event()
    calls, outcomes = [], []

    class HoldingBridge:
        def once(self):
            calls.append('once')
            entered.set()
            assert release.wait(5)
            return {'status': 'blocked', 'run_id': entry['bridge_run_id']}

    thread = threading.Thread(target=lambda: outcomes.append(
        BridgeQueue(TaskStore(store.root)).dispatch_one(lambda *_: HoldingBridge())))
    thread.start()
    try:
        assert entered.wait(5)
        contender = BridgeQueue(TaskStore(store.root))
        denied = contender.dispatch_one(lambda *_: (_ for _ in ()).throw(AssertionError('duplicate factory')))
        assert denied['status'] == 'blocked' and denied['reason'] == 'queue consumer busy'
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and outcomes[0]['status'] == 'blocked'
    assert calls == ['once'] and store.load(entry['id'])['invocations'] == 1


def test_preexisting_bridge_state_blocks_before_invocation(tmp_path):
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    queue = BridgeQueue(store)
    entry = queue.enqueue(source, authorization, context, runner_commit=head)
    state = store.root / entry['id'] / 'bridge'
    state.mkdir()
    (state / 'journal.sqlite3').write_bytes(b'partial or prior execution')
    denied = queue.dispatch_one(lambda *_: (_ for _ in ()).throw(AssertionError('duplicate factory')))
    assert denied['status'] == 'blocked'
    assert store.load(entry['id'])['invocations'] == 0
    assert (state / 'journal.sqlite3').read_bytes() == b'partial or prior execution'


def test_interrupted_enqueue_orphan_blocks_dispatch_without_erasing_evidence(tmp_path):
    from bridge_queue import BridgeQueue
    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    entry = BridgeQueue(store).enqueue(source, authorization, context, runner_commit=head)
    orphan = store.root / ('e' * 32)
    orphan.mkdir(mode=0o700)
    denied = BridgeQueue(store).dispatch_one(
        lambda *_: (_ for _ in ()).throw(AssertionError('must not start existing task')))
    assert denied == {'status': 'blocked', 'reason': 'queue state incomplete or invalid'}
    assert orphan.is_dir()
    assert store.load(entry['id'])['status'] == 'queued'


def test_missing_or_unknown_status_blocks_all_dispatch(tmp_path):
    from bridge_queue import BridgeQueue
    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    queue = BridgeQueue(store)
    entry = queue.enqueue(source, authorization, context, runner_commit=head)
    invalid_id = 'd' * 32
    store.create_entry_directory(invalid_id)
    store.save({'id': invalid_id, 'kind': 'bridge', 'created_ns': 0})
    denied = queue.dispatch_one(lambda *_: (_ for _ in ()).throw(AssertionError('called')))
    assert denied == {'status': 'blocked', 'reason': 'queue state incomplete or invalid'}
    store.save({'id': invalid_id, 'kind': 'bridge', 'created_ns': 0, 'status': 'mystery'})
    denied = queue.dispatch_one(lambda *_: (_ for _ in ()).throw(AssertionError('called')))
    assert denied == {'status': 'blocked', 'reason': 'queue state incomplete or invalid'}
    assert store.load(entry['id'])['status'] == 'queued'


def test_observer_does_not_create_absent_queue_root(tmp_path):
    from queue_store import monitor_snapshot
    root = tmp_path / 'absent'
    counts = monitor_snapshot(root)
    assert counts == {'queued': 0, 'running': 0, 'blocked': 0,
                      'review-ready': 0, 'completed': 0}
    assert not root.exists()


def test_observer_never_creates_root_if_it_disappears_after_existence_probe(tmp_path, monkeypatch):
    import pytest
    from queue_store import monitor_snapshot
    root = tmp_path / 'absent'
    original_exists = Path.exists
    once = [True]

    def raced_exists(path, *args, **kwargs):
        if path == root and once[0]:
            once[0] = False
            return True
        return original_exists(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'exists', raced_exists)
    with pytest.raises(FileNotFoundError):
        monitor_snapshot(root)
    assert not original_exists(root)


def test_enqueue_fsyncs_queue_directory_before_publishing_state(tmp_path, monkeypatch):
    import queue_store
    import bridge_queue
    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    root_identity = (store.root.stat().st_dev, store.root.stat().st_ino)
    observed = []
    original_fsync = queue_store.os.fsync
    original_save = store.save

    def tracked_fsync(fd):
        info = queue_store.os.fstat(fd)
        if (info.st_dev, info.st_ino) == root_identity:
            observed.append('root')
        return original_fsync(fd)

    def checked_save(item):
        assert observed == ['root'], 'entry directory not durable before state publication'
        return original_save(item)

    monkeypatch.setattr(queue_store.os, 'fsync', tracked_fsync)
    monkeypatch.setattr(store, 'save', checked_save)
    bridge_queue.BridgeQueue(store).enqueue(source, authorization, context, runner_commit=head)
    assert observed == ['root']


def test_read_only_observer_counts_review_ready_separately(tmp_path):
    from queue_store import monitor_snapshot
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    entry = BridgeQueue(store).enqueue(source, authorization, context, runner_commit=head)
    saved = store.load(entry['id'])
    saved.update(status='review-ready', ci='pending')
    store.save(saved)
    counts = monitor_snapshot(store.root)
    assert counts['review-ready'] == 1
    assert counts['completed'] == 0 and counts['blocked'] == 0


def test_blocked_bridge_retains_bounded_result_and_publication_intent(tmp_path):
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    queue = BridgeQueue(store)
    entry = queue.enqueue(source, authorization, context, runner_commit=head)
    intent = {'stage': 'intent', 'expected_head': 'b' * 40,
              'number': None, 'url': None}

    class FakeBridge:
        def once(self):
            return {'status': 'blocked', 'run_id': entry['bridge_run_id'],
                    'base': head, 'head': 'b' * 40, 'pr_url': None,
                    'ci': 'pending', 'reason': 'untrusted raw exception could contain a secret'}

        def _pr_creation(self):
            return intent

    assert queue.dispatch_one(lambda *_: FakeBridge())['status'] == 'blocked'
    saved = store.load(entry['id'])
    assert saved['bridge_result'] == {
        'status': 'blocked', 'run_id': entry['bridge_run_id'],
        'base': head, 'head': 'b' * 40, 'ci': 'pending'}
    assert saved['receipt'] == intent
    assert 'untrusted raw exception' not in json.dumps(saved)


def test_claim_write_failure_never_constructs_a_bridge(tmp_path, monkeypatch):
    import pytest
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    entry = BridgeQueue(store).enqueue(source, authorization, context, runner_commit=head)
    monkeypatch.setattr(store, 'save', lambda _item: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError, match='disk full'):
        BridgeQueue(store).dispatch_one(lambda *_: (_ for _ in ()).throw(AssertionError('factory called')))
    assert store.load(entry['id'])['status'] == 'queued'
    assert store.load(entry['id'])['invocations'] == 0


def test_crash_after_bridge_returns_but_before_queue_receipt_save_blocks_restart(tmp_path, monkeypatch):
    import pytest
    from bridge_queue import BridgeQueue

    source, authorization, context, head = reviewed_fixture(tmp_path)
    store = TaskStore(tmp_path / 'queue')
    entry = BridgeQueue(store).enqueue(source, authorization, context, runner_commit=head)
    original_save = store.save
    calls = []
    url = 'https://github.com/aliercankonus/signal-desk-prediction/pull/99'

    def fail_final_write(item):
        if item['status'] == 'review-ready':
            raise OSError('disk full after Bridge')
        original_save(item)

    class FakeBridge:
        def once(self):
            calls.append('once')
            return {'status': 'review-ready', 'run_id': entry['bridge_run_id'],
                    'base': head, 'head': 'b' * 40, 'pr_url': url, 'ci': 'pending'}

        def _pr_creation(self):
            return {'stage': 'verified', 'expected_head': 'b' * 40,
                    'number': 99, 'url': url}

    monkeypatch.setattr(store, 'save', fail_final_write)
    with pytest.raises(OSError, match='disk full after Bridge'):
        BridgeQueue(store).dispatch_one(lambda *_: FakeBridge())
    assert store.load(entry['id'])['status'] == 'running'
    assert BridgeQueue(TaskStore(store.root)).dispatch_one(
        lambda *_: (_ for _ in ()).throw(AssertionError('redispatched')))['status'] == 'blocked'
    assert calls == ['once']
