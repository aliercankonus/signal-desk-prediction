"""Review-only operator contract; never invoke a real host or Docker daemon."""
from pathlib import Path
import os
import shutil
import socket
import subprocess
import re
import json

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/review/vps-research-copy-extract.sh"
REQUIRED = (
    "RESEARCH_RECOVERY_EVIDENCE", "RESEARCH_ORIGINAL_EVIDENCE", "RESEARCH_WORK_PARENT",
    "RESEARCH_CHECKOUT_PARENT", "RESEARCH_REMOTE", "RESEARCH_IMAGE_REPO",
    "RESEARCH_ACTIVE_SETTINGS", "RESEARCH_CANDIDATE_SETTINGS", "RESEARCH_GUARD",
    "RESEARCH_EXPECTED_HOST", "RESEARCH_AGENT_NAME_FILTER",
)


def test_shell_parses_and_required_inputs_fail_before_any_side_effect(tmp_path):
    assert subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True).returncode == 0
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("docker", "git", "python3"):
        path = bin_dir / name
        path.write_text("#!/bin/sh\nprintf '%s\\n' invoked >> \"$MOCK_CALLS\"\nexit 77\n")
        path.chmod(0o755)
    calls = tmp_path / "calls"
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", MOCK_CALLS=str(calls))
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert not calls.exists(), result.stderr


def test_unprotected_script_copy_rejected_before_docker(tmp_path):
    stage = tmp_path / "staged"
    stage.mkdir()
    script = stage / SCRIPT.name
    shutil.copyfile(SCRIPT, script)
    for name in ("research_copy_gates.py", "soak_recovery_gates.py", "soak_gates.py", "acceptance_gates.py"):
        (stage / name).write_text("# synthetic mock; must not execute\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("docker", "git", "id", "realpath", "python3", "hostname"):
        path = bin_dir / name
        path.write_text("#!/bin/sh\nprintf '%s\\n' invoked >> \"$MOCK_CALLS\"\nexit 77\n")
        path.chmod(0o755)
    calls = tmp_path / "calls"
    values = {key: str(tmp_path) for key in REQUIRED}
    values.update(RESEARCH_IMAGE_REPO="research", RESEARCH_REMOTE="file:///synthetic",
                  RESEARCH_EXPECTED_HOST=socket.gethostname(), RESEARCH_AGENT_NAME_FILTER="agent",
                  RESEARCH_EXPECTED_ACTIVE_HEAD="a" * 40, RESEARCH_APPROVAL_SHA256="b" * 64,
                  RESEARCH_SOURCE_IDLE_CONFIRMED="operator-verified-exclusive-writer-control-and-source-idle",
                  RESEARCH_PRIOR_EVIDENCE=str(tmp_path), RESEARCH_CONFIG_DIR=str(tmp_path),
                  RESEARCH_BASE_IMAGE_ID="sha256:" + "c" * 64)
    env = dict(os.environ, **values, PATH=f"{bin_dir}:{os.environ['PATH']}", MOCK_CALLS=str(calls))
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert not calls.exists(), result.stderr


def test_protected_preflight_and_existing_source_only():
    text = SCRIPT.read_text()
    assert all(name in text for name in REQUIRED)
    assert "5696c6cd17c4dc808c7fd3e42c47fc131f3873f3" in text
    assert "research_copy_gates.py" in text
    assert "soak_recovery_gates.py" in text and "soak_gates.py" in text
    assert "candidate-config.sha256" in text
    assert "4728798c9c8668375f793db906fe9277ad4bb409f9ddb99f2b3c8d477326a27f" in text
    assert "ad19e237bc6c816a1a218cf269fdfce06248c693a95437016bedba2ef34a09a4" in text
    assert "575571200739f6d3aeacb22aba7faa09e3b855449872cb7484ca891f49fe6a48" in text
    assert "--recovery" in text and "--original" in text and "--raw-dir" in text
    assert "--verified" in text and "--copy-dir" in text and "--manifest-out" in text
    assert "outside_agent_mount" in text and "protected_path" in text
    assert "no_host_collector" in text and "no_other_volume_users" in text
    assert "no_host_volume_writers" in text and "/proc" in text and "fdinfo" in text
    assert "os.O_ACCMODE" in text and "timeout 30s python3" in text
    for prohibited in ("docker compose up", "docker compose down", "audit_raw", "replay.session",
                       "chmod -R", "--privileged"):
        assert prohibited not in text


def test_proc_writer_scan_rejects_writable_fd_with_synthetic_proc(tmp_path):
    import re
    text = SCRIPT.read_text()
    match = re.search(r'no_host_volume_writers\(\) \{.*?<<\x27PY\x27\n(.*?)\nPY', text, re.S)
    assert match
    scanner = match.group(1).replace("proc = pathlib.Path('/proc')", "proc = pathlib.Path(sys.argv[2])")
    volume = tmp_path / "volume"
    volume.mkdir()
    raw = volume / "raw.jsonl"
    raw.write_bytes(b"raw\n")
    proc = tmp_path / "proc"
    fd = proc / "123" / "fd"
    fd.mkdir(parents=True)
    (proc / "123" / "fdinfo").mkdir()
    (fd / "7").symlink_to(raw)
    flags = proc / "123" / "fdinfo" / "7"
    flags.write_text("flags:\t0100002\n")
    run = lambda: subprocess.run(["python3", "-", str(volume), str(proc)], input=scanner,
                                 capture_output=True, text=True)
    assert run().returncode != 0
    flags.write_text("flags:\t0100000\n")
    assert run().returncode == 0


def test_extraction_is_isolated_bounded_and_retains_failure_evidence():
    text = SCRIPT.read_text()
    assert "docker build" in text and "docker image inspect" in text
    assert "--network none" in text and "--read-only" in text
    assert "--memory" in text and "--cpus" in text and "--pids-limit" in text
    assert "--mount" in text and "readonly" in text
    assert 'source=$RUN/completed.json,target=/app/docs/research/completed-raw-copy-v1.json,readonly' in text
    assert 'source=$RUN/output,target=/result' in text
    assert 'source=$RUN,target=/result' not in text
    assert 'source=$RUN,target=/evidence' not in text
    assert "--cidfile" in text and "--kill-after" in text
    assert "signal_desk.research.extract_prefix" in text
    assert "research-input-v1.json" in text
    assert "verify_source" in text and "trap finish EXIT" in text
    assert "docker rm" not in text and "rm -rf" not in text


def test_private_operator_command_context_and_logs_are_retained():
    text = SCRIPT.read_text()
    assert '"$RUN/operator-context.json"' in text
    assert '"$RUN/reviewed-procedure.sh"' in text
    assert '"$RUN/operator.log"' in text
    assert '"$RUN/build.log"' in text
    assert '"$RUN/extract.stdout.log"' in text
    assert '"$RUN/extract.stderr.log"' in text


def test_only_the_extractor_starts_a_container():
    text = SCRIPT.read_text()
    assert text.count('docker run ') == 1
    assert 'docker run --rm' not in text
    assert 'pip freeze' not in text
    assert 'dpkg-query' not in text


def test_inherited_path_and_python_environment_are_cleared_before_external_commands():
    text = SCRIPT.read_text()
    assert re.search(r'set -Eeuo pipefail\nPATH=/usr/sbin:/usr/bin:/sbin:/bin\nexport PATH\nunset BASH_ENV ENV PYTHONPATH', text)
    assert text.index('export PATH') < text.index('$(id -u)')
    assert text.index('unset BASH_ENV') < text.index('$(id -u)')


def test_api_writable_volume_exemption_requires_known_health_command_and_health():
    text = SCRIPT.read_text()
    assert "signal_desk.api.health_server" in text
    assert "item.get('Destination') == '/data'" in text
    assert "item.get('RW') is False" in text
    assert "State.Health.Status" in text
    assert 'API_IMAGE' in text
    assert 'no_host_volume_writers' in text


def test_base_image_is_operator_pinned_and_dependency_provenance_reviewed():
    text = SCRIPT.read_text()
    assert 'RESEARCH_BASE_IMAGE_ID' in text
    assert 'python:3.12-slim' in text
    assert text.count('docker image inspect --format \'{{.Id}}\' python:3.12-slim') >= 2
    assert 'build-provenance.json' in text and 'image-layers.json' in text
    assert 'dockerfile_sha256' in text and 'requirements_sha256' in text
    assert 'RESEARCH_BUILD_PROVENANCE_REVIEWED' in text
    assert text.index('RESEARCH_BUILD_PROVENANCE_REVIEWED') < text.index('docker run --name')


def test_output_gate_is_staged_and_called_after_docker_success():
    text = SCRIPT.read_text()
    assert 'research_output_gates.py' in text
    assert '"$OUTPUT_GATES" validate' in text
    assert text.index('"$OUTPUT_GATES" validate') > text.index('>"$RUN/extract.stdout.log"')
    assert text.index('"$OUTPUT_GATES" validate') < text.index('verify_active', text.index('>"$RUN/extract.stdout.log"'))
    assert '--raw-copy-dir "$RUN/raw-copy"' in text
    assert 'timeout 1200s python3 "$OUTPUT_GATES" validate' in text
    assert 'ulimit -v 2097152' in text


def _extraction_harness(tmp_path, *, gate_failure=True, existing_quarantine=False,
                        unknown_container=False, fail_final_verification=False):
    """Run only the copied trap/extraction fragment with mock shell functions, never the host preflight."""
    text = SCRIPT.read_text()
    finish = re.search(r'finish\(\) \{\n.*?\n\}\ntrap finish EXIT', text, re.S)
    assert finish
    body = text[text.index('mkdir -- "$RUN/output"'):]
    run = tmp_path / 'private-run'
    run.mkdir()
    if existing_quarantine:
        (run / 'incomplete-output').mkdir()
        (run / 'incomplete-output' / 'prior').write_bytes(b'leave untouched')
    prelude = r'''
set -Eeuo pipefail
RUN=$1
SID=fixture
CURRENT_NAME=fixture
CURRENT_CIDFILE="$RUN/fixture.cid"
IMAGE_ID=sha256:fixture
OUTPUT_GATES=fixture-output-gates
CHECKOUT=fixture-checkout
verify_active() { :; }
verify_source() { printf 'source checked\n' > "$1"; }
timeout() {
  case " $* " in
    *" docker run "*)
      mkdir -p "$RUN/output/prefix"
      printf 'unvalidated partial bytes\n' > "$RUN/output/prefix/research-input-v1.json"
      printf '%064d' 0 > "$CURRENT_CIDFILE"
      return 0 ;;
    *" fixture-output-gates validate "*) printf 'gate rejected\n' >&2; return 7 ;;
    *" docker inspect "*) printf '%064d|%s|%s|/%s|false\n' 0 "$IMAGE_ID" "$SID" "$CURRENT_NAME" ;;
    *" docker stop "*) printf 'stop attempted\n' >> "$RUN/docker-stop.calls"; return 0 ;;
    *) return 0 ;;
  esac
}
'''
    # This executes the real script's finish and extraction fragments only; no root preflight,
    # source access, Docker command or host process scan can run in this harness.
    fragment = prelude + finish.group(0) + '\ntrap \'exit 130\' INT\ntrap \'exit 143\' TERM\n' + body
    if not gate_failure:
        fragment = fragment.replace("printf 'gate rejected\\n' >&2; return 7", "return 0")
    if unknown_container:
        fragment = fragment.replace("printf '%064d|%s|%s|/%s|false\\n' 0 \"$IMAGE_ID\" \"$SID\" \"$CURRENT_NAME\"", "printf 'unknown\\n'")
    if fail_final_verification:
        fragment = fragment.replace('verify_active() { :; }', 'verify_active() { return 6; }')
    result = subprocess.run(['bash', '-c', fragment, 'harness', str(run)], capture_output=True, text=True)
    return run, result


def test_false_zero_exit_extractor_output_gate_failure_quarantines_partial_bytes(tmp_path):
    run, result = _extraction_harness(tmp_path)
    assert result.returncode != 0
    assert 'gate rejected' in result.stderr
    assert not (run / 'output').exists()
    assert (run / 'incomplete-output/prefix/research-input-v1.json').read_bytes() == b'unvalidated partial bytes\n'


def test_failure_does_not_overwrite_existing_quarantine(tmp_path):
    run, result = _extraction_harness(tmp_path, existing_quarantine=True)
    assert result.returncode != 0
    assert (run / 'incomplete-output/prior').read_bytes() == b'leave untouched'
    assert not (run / 'output/prefix/research-input-v1.json').exists()
    assert b'unvalidated partial bytes\n' in [p.read_bytes() for p in run.rglob('research-input-v1.json')]


def test_success_keeps_validated_output_at_original_path(tmp_path):
    run, result = _extraction_harness(tmp_path, gate_failure=False)
    assert result.returncode == 0, result.stderr
    assert (run / 'output/prefix/research-input-v1.json').exists()
    assert not (run / 'incomplete-output').exists()


def test_post_gate_identity_failure_also_quarantines_output(tmp_path):
    run, result = _extraction_harness(tmp_path, gate_failure=False, fail_final_verification=True)
    assert result.returncode != 0
    assert not (run / 'output').exists()
    assert (run / 'incomplete-output/prefix/research-input-v1.json').exists()


def test_unknown_container_is_warned_and_not_stopped_but_output_is_quarantined(tmp_path):
    run, result = _extraction_harness(tmp_path, unknown_container=True)
    assert result.returncode != 0
    assert 'Container identity unconfirmed' in result.stderr
    assert not (run / 'docker-stop.calls').exists()
    assert not (run / 'output').exists()
    assert (run / 'incomplete-output/prefix/research-input-v1.json').exists()


def test_exclusive_writer_control_attestation_is_required():
    text = SCRIPT.read_text()
    assert 'operator-verified-exclusive-writer-control-and-source-idle' in text
    assert 'operator-verified-collector-stopped-and-source-idle' not in text
    assert 'docker exec' in text and 'privileged writer' in text


def test_source_verifier_receives_independent_approval_anchor():
    text = SCRIPT.read_text()
    assert '--expected-approval-sha256 "$RESEARCH_APPROVAL_SHA256"' in text


def test_api_writable_mount_gate_with_synthetic_docker_inspection(tmp_path):
    text = SCRIPT.read_text()
    match = re.search(r'no_other_volume_users\(\) \{.*?<<\x27PY\x27\n(.*?)\nPY', text, re.S)
    assert match
    code = match.group(1).replace('sys.argv[1:]; root', 'sys.argv[1:5]; root')
    api = 'a' * 64
    image = 'sha256:' + 'b' * 64
    info = {'Id': api, 'Image': image,
            'State': {'Running': True, 'Health': {'Status': 'healthy'}},
            'Config': {'Entrypoint': None, 'Cmd': ['python', '-m', 'signal_desk.api.health_server',
                                                    '--host', '0.0.0.0', '--port', '8080'],
                       'Labels': {'com.docker.compose.service': 'api'}},
            'Mounts': [{'Source': str(tmp_path), 'Name': 'volume', 'Destination': '/data', 'RW': True}]}
    def run(payload):
        harness = ("import subprocess, json, sys\nsubprocess.check_output = lambda args, **kwargs: ('" + api +
                   "\\n' if args[1] == 'ps' else json.dumps([json.loads(sys.argv[5])]))\n")
        return subprocess.run(['python3', '-', 'volume', str(tmp_path), api, image, json.dumps(payload)],
                              input=harness + code, capture_output=True, text=True)
    assert run(info).returncode == 0
    wrong = json.loads(json.dumps(info))
    wrong['Config']['Cmd'][-1] = '8081'
    assert run(wrong).returncode != 0
    unhealthy = json.loads(json.dumps(info))
    unhealthy['State']['Health']['Status'] = 'unhealthy'
    assert run(unhealthy).returncode != 0
    other = json.loads(json.dumps(info))
    other['Mounts'][0]['Destination'] = '/raw'
    assert run(other).returncode != 0
