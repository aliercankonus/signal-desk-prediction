#!/usr/bin/env bash
# Standalone bootstrap: existing checkout or fresh public clone.
set -Eeuo pipefail
repository_url=https://github.com/aliercankonus/signal-desk-prediction.git
repo_dir=""
requested_ref=""
install_docker=0
plan=0
expected_host=""
deploy_args=()
while (($#)); do
  case "$1" in
    --dir) repo_dir="${2:?missing directory}"; shift 2 ;;
    --ref) requested_ref="${2:?missing ref}"; shift 2 ;;
    --install-docker) install_docker=1; shift ;;
    --plan) plan=1; shift ;;
    --expected-host) expected_host="${2:?missing hostname}"; deploy_args+=("$1" "$expected_host"); shift 2 ;;
    --project|--port|--bind) deploy_args+=("$1" "${2:?missing argument}"); shift 2 ;;
    --no-smoke) deploy_args+=("$1"); shift ;;
    -h|--help) echo "usage: install.sh [--dir PATH] [--ref REF] [--install-docker] [--project NAME] [--port PORT] [--bind ADDRESS] [--expected-host HOST] [--no-smoke] [--plan]"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
die() { echo "ERROR: $*" >&2; exit 1; }
if [[ -z "$repo_dir" ]]; then
  source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd -P || true)
  if [[ -n "$source_dir" && -d "$source_dir/.git" && -f "$source_dir/docker-compose.yml" ]]; then
    repo_dir="$source_dir"
  elif [[ -d "$PWD/.git" && -f "$PWD/docker-compose.yml" ]]; then
    repo_dir="$PWD"
  else
    repo_dir=/opt/signal-desk-prediction
  fi
fi
repo_dir=$(realpath -m -- "$repo_dir")
if ((plan)); then
  printf 'repo=%s\nref=%s\ninstall_docker_if_missing=%s\n' "$repo_dir" "${requested_ref:-existing checkout or main}" "$install_docker"
  echo "steps=host check, prerequisites, clone/reuse, config, build, validation, tests, optional smoke, API health, local manifest"
  exit 0
fi
command -v systemd-detect-virt >/dev/null || die "Run on a supported Ubuntu/Linux host"
if systemd-detect-virt --container --quiet; then
  die "This is a container. Run the bootstrap on the VPS host."
fi
[[ -z "$expected_host" || "$(hostname)" == "$expected_host" ]] || die "Hostname does not match --expected-host"
if ((install_docker)) && ! command -v docker >/dev/null; then
  [[ "$EUID" -eq 0 ]] || die "--install-docker requires root"
  . /etc/os-release
  [[ "$ID" == ubuntu && ( "$VERSION_ID" == 22.04 || "$VERSION_ID" == 24.04 ) ]] || die "Automatic Docker setup supports fresh Ubuntu 22.04/24.04 only"
  # Refuse conflicting installations; never uninstall another workload's runtime.
  for package in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
    if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
      die "Conflicting package $package; no automatic replacement performed"
    fi
  done
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl git
  [[ ! -e /etc/apt/sources.list.d/docker.sources && ! -e /etc/apt/sources.list.d/docker.list ]] || die "Existing Docker source requires manual inspection"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi
command -v docker >/dev/null || die "Docker missing; use --install-docker on a fresh supported host"
docker info >/dev/null || die "No Docker daemon access; do not install a second Docker inside an agent container"
docker compose version >/dev/null || die "Compose plugin missing; existing Docker was left unchanged"
docker buildx version >/dev/null || die "Buildx plugin missing; existing Docker was left unchanged"
command -v git >/dev/null || die "git is required"
fresh=0
if [[ -d "$repo_dir/.git" ]]; then
  git_here() { git -c "safe.directory=$repo_dir" -C "$repo_dir" "$@"; }
  remote=$(git_here remote get-url origin)
  [[ "$remote" == "$repository_url" || "$remote" == "${repository_url%.git}" ]] || die "Existing checkout origin does not match this project"
  if [[ -n "$requested_ref" ]]; then
    git_here diff --quiet HEAD -- . ':(exclude)config/config.yaml' || die "Tracked code changes prevent ref update"
    git_here fetch -- origin "$requested_ref"
    git_here checkout --detach FETCH_HEAD
  fi
else
  if [[ -e "$repo_dir" && -n "$(ls -A "$repo_dir")" ]]; then
    die "Target is nonempty and not this project's checkout"
  fi
  mkdir -p -- "$(dirname -- "$repo_dir")"
  git clone -- "$repository_url" "$repo_dir"
  fresh=1
  if [[ -n "$requested_ref" ]]; then
    git -c "safe.directory=$repo_dir" -C "$repo_dir" fetch -- origin "$requested_ref"
    git -c "safe.directory=$repo_dir" -C "$repo_dir" checkout --detach FETCH_HEAD
  fi
fi
[[ -f "$repo_dir/scripts/deploy.sh" ]] || die "Selected ref lacks deploy.sh; use the installer release/ref"
if ((fresh)); then deploy_args+=(--initialize-config); fi
exec bash "$repo_dir/scripts/deploy.sh" "${deploy_args[@]}"

