#!/usr/bin/env python3
"""Fail-closed verification of a root-approved, immutable host release.

This is installed root-owned outside the repository. It never updates Git refs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys


class ReleaseError(Exception):
    """A release is not approved or is no longer protected."""


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_path(path, owner_uid=0, tree=False):
    """Reject symlinks, unapproved owners, and replaceable/writable ancestors."""
    path = Path(path)
    require(path.is_absolute() and str(path) == os.path.normpath(str(path)), "Non-canonical protected path")
    allowed = {0, owner_uid} if owner_uid else {0}
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except OSError as exc:
            raise ReleaseError(f"Missing protected path: {item}") from exc
        require(not stat.S_ISLNK(info.st_mode), f"Symlink in protected path: {item}")
        require(info.st_uid in allowed, f"Unapproved owner: {item}")
        require(not info.st_mode & 0o022, f"Writable protected path: {item}")
    if tree:
        for base, directories, files in os.walk(path, followlinks=False):
            for name in directories + files:
                item = Path(base) / name
                info = item.lstat()
                require(not stat.S_ISLNK(info.st_mode), f"Symlink in release: {item}")
                require(info.st_uid in allowed, f"Unapproved owner: {item}")
                require(not info.st_mode & 0o022, f"Writable release input: {item}")
    return path


def run(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode:
        raise ReleaseError(f"Required command failed: {args[0]} {args[1] if len(args) > 1 else ''}")
    return result.stdout.strip()


def container_id(name):
    value = run("docker", "inspect", "--format", "{{.Id}}", name)
    require(bool(re.fullmatch(r"[a-f0-9]{64}", value)), "Invalid agent container identity")
    return value


def agent_mounts(identifier):
    require(bool(re.fullmatch(r"[a-f0-9]{64}", identifier)), "Invalid agent container identity")
    require(container_id(identifier) == identifier, "Agent container identity changed")
    # Also inspect running/recent Hermes containers; a replacement must not
    # gain a new bind mount that bypasses the approved container's mount list.
    candidates = [identifier] + [item for item in run("docker", "ps", "-aq", "--filter", "name=hermes-agent").splitlines()
                                 if item and item != identifier]
    sources = []
    for item in candidates:
        output = run("docker", "inspect", "--format", "{{range .Mounts}}{{println .Source}}{{end}}", item)
        sources.extend(line for line in output.splitlines() if line)
    return sources


def volume_identity(project, require_active=False):
    name = f"{project}_signal_desk_data"
    identity = run("docker", "volume", "inspect", "--format", "{{.Mountpoint}}|{{.CreatedAt}}", name)
    require(bool(identity) and "|" in identity and all(identity.split("|", 1)),
            "Existing data volume identity unavailable")
    if require_active:
        containers = run("docker", "ps", "--filter", f"label=com.docker.compose.project={project}",
                         "--filter", "label=com.docker.compose.service=api", "--format", "{{.ID}}")
        require(len(containers.splitlines()) == 1, "Exactly one existing API container required")
        attached = run("docker", "inspect", "--format",
                       '{{range .Mounts}}{{if eq .Destination "/data"}}{{println .Name .Source}}{{end}}{{end}}',
                       containers)
        require(attached.split()[:2] == [name, identity.split("|", 1)[0]],
                "Existing API is not using the pinned data volume")
    return identity


def outside_agent_mount(path, mount_sources):
    path = Path(path).resolve()
    for source in mount_sources:
        source_path = Path(source).resolve()
        if path == source_path or path.is_relative_to(source_path) or source_path.is_relative_to(path):
            raise ReleaseError(f"Release overlaps agent mount: {source_path}")


def protected_host_destination(path, mount_sources):
    outside_agent_mount(path, mount_sources)
    candidate = Path(path)
    while not candidate.exists() and not candidate.is_symlink():
        candidate = candidate.parent
    protected_path(candidate)


def git(repo, *args):
    return run("git", "-c", f"safe.directory={repo}", "-C", str(repo), *args)


def paper_config(path):
    """Conservative project-block guard; application validation is still required."""
    lines = path.read_text(encoding="utf-8").splitlines()
    project_blocks = 0
    in_project = False
    mode = []
    execution = []
    for line in lines:
        if line == "project:":
            project_blocks += 1
            in_project = True
        elif line and not line[0].isspace() and not line.startswith("#"):
            in_project = False
        elif in_project:
            if line.startswith("  mode:"):
                mode.append(line)
            if line.startswith("  execution_enabled:"):
                execution.append(line)
    require(project_blocks == 1 and mode == ["  mode: paper"] and
            execution == ["  execution_enabled: false"], "Paper-only config required")


def project_env(path, project):
    lines = path.read_text(encoding="utf-8").splitlines()
    values = {}
    for key in ("COMPOSE_PROJECT_NAME", "SDP_API_PORT", "SDP_BIND_ADDRESS"):
        matches = [line.split("=", 1)[1] for line in lines if line.startswith(key + "=")]
        require(len(matches) == 1, f"Missing or duplicate {key} in approved .env")
        values[key] = matches[0]
    require(values["COMPOSE_PROJECT_NAME"] == project, "Existing Compose project mismatch")
    require(bool(re.fullmatch(r"[0-9]{1,5}", values["SDP_API_PORT"])) and
            1 <= int(values["SDP_API_PORT"]) <= 65535, "Invalid approved API port")
    require(values["SDP_BIND_ADDRESS"] in ("127.0.0.1", "0.0.0.0"), "Invalid approved bind address")


def verify_release(settings, owner_uid=0, mount_sources=None, settings_path=None,
                   observed_volume_identity=None):
    """Verify approved identity, immutable code/config, ownership and isolation."""
    needed = {"repo", "approved_commit", "project", "expected_host", "agent_container_id",
              "env_sha256", "config_sha256", "volume_identity"}
    require(isinstance(settings, dict) and set(settings) == needed, "Invalid release settings")
    repo = Path(settings["repo"])
    sha = settings["approved_commit"]
    require(bool(re.fullmatch(r"[a-f0-9]{40}", sha)), "A full approved commit SHA is required")
    require(bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]*", settings["project"])), "Invalid project")
    require(bool(re.fullmatch(r"[a-f0-9]{64}", settings["agent_container_id"])), "Invalid agent container ID")
    require(socket.gethostname() == settings["expected_host"], "Unexpected host")
    protected_path(repo, owner_uid=owner_uid, tree=True)
    sources = agent_mounts(settings["agent_container_id"]) if mount_sources is None else mount_sources
    outside_agent_mount(repo, sources)
    if settings_path is not None:
        protected_host_destination(settings_path, sources)
    for destination in ("/usr/local/libexec/signal-desk", "/etc/signal-desk",
                        "/etc/sudoers.d/signal-desk-host-gateway"):
        protected_host_destination(destination, sources)
    observed = (volume_identity(settings["project"]) if observed_volume_identity is None
                else observed_volume_identity)
    require(observed == settings["volume_identity"], "Existing data volume identity changed")
    require((repo / ".git").is_dir() and (repo / "docker-compose.yml").is_file(), "Release checkout missing")
    require(git(repo, "rev-parse", "HEAD") == sha, "Checkout differs from approved commit")
    require(git(repo, "cat-file", "-t", sha) == "commit", "Approved object is not a commit")
    require(not git(repo, "diff", "--name-only", "HEAD", "--", ".", ":(exclude)config/config.yaml"),
            "Tracked code differs from approved commit")
    require(not git(repo, "ls-files", "--others", "--exclude-standard"), "Untracked release files")
    env = repo / ".env"
    config = repo / "config/config.yaml"
    require(env.is_file() and config.is_file(), "Approved configuration missing")
    require(sha256(env) == settings["env_sha256"], "Approved .env hash mismatch")
    require(sha256(config) == settings["config_sha256"], "Approved config hash mismatch")
    project_env(env, settings["project"])
    paper_config(config)
    return str(repo), settings["project"], settings["expected_host"]


def load_settings(path):
    path = protected_path(path)
    require(path.stat().st_mode & 0o077 == 0, "Release settings must be root-only")
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("verify")
    check.add_argument("--settings", required=True)
    check.add_argument("--auth-path")
    destination = sub.add_parser("check-checkout")
    destination.add_argument("--dir", required=True)
    destination.add_argument("--commit", required=True)
    destination.add_argument("--config-dir", required=True)
    destination.add_argument("--agent-container", required=True)
    destination.add_argument("--project", required=True)
    destination.add_argument("--settings", required=True)
    approve = sub.add_parser("approve")
    for option in ("repo", "approved-commit", "project", "expected-host", "agent-container-id", "settings"):
        approve.add_argument("--" + option, required=True)
    args = parser.parse_args()
    try:
        require(os.geteuid() == 0, "Root terminal required")
        if args.command == "verify":
            fields = verify_release(load_settings(args.settings), settings_path=args.settings)
            if args.auth_path:
                outside_agent_mount(args.auth_path, agent_mounts(load_settings(args.settings)["agent_container_id"]))
            require(all("\n" not in value for value in fields), "Invalid settings field")
            print("\n".join(fields))
        elif args.command == "check-checkout":
            target = protected_path(args.dir, tree=True)
            require((target / ".git").is_dir(), "Prepared Git checkout missing")
            require(bool(re.fullmatch(r"[a-f0-9]{40}", args.commit)), "A full approved commit SHA is required")
            require(git(target, "rev-parse", "HEAD") == args.commit, "Checkout differs from approved commit")
            require(not git(target, "status", "--porcelain", "--untracked-files=all"), "Prepared checkout is not clean")
            protected_path(args.config_dir, tree=True)
            for name in (".env", "config.yaml"):
                source = Path(args.config_dir) / name
                require(source.is_file() and source.stat().st_mode & 0o077 == 0,
                        f"Operator-approved {name} must be root-only")
            project_env(Path(args.config_dir) / ".env", args.project)
            paper_config(Path(args.config_dir) / "config.yaml")
            sources = agent_mounts(container_id(args.agent_container))
            outside_agent_mount(target, sources)
            outside_agent_mount(args.config_dir, sources)
            for destination_path in (args.settings, "/usr/local/libexec/signal-desk",
                                     "/etc/signal-desk", "/etc/sudoers.d/signal-desk-host-gateway"):
                protected_host_destination(destination_path, sources)
            volume_identity(args.project, require_active=True)
        else:
            require(not Path(args.settings).exists(), "Release approval already exists")
            protected_path(Path(args.settings).parent)
            settings = {
                "repo": args.repo, "approved_commit": args.approved_commit,
                "project": args.project, "expected_host": args.expected_host,
                "agent_container_id": args.agent_container_id,
                "env_sha256": sha256(Path(args.repo) / ".env"),
                "config_sha256": sha256(Path(args.repo) / "config/config.yaml"),
                "volume_identity": volume_identity(args.project, require_active=True),
            }
            verify_release(settings, settings_path=args.settings)
            fd = os.open(args.settings, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(settings, stream, sort_keys=True)
                stream.write("\n")
            print("RELEASE_APPROVED", settings["approved_commit"], "(configuration contents not logged)")
    except (ReleaseError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Release verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
