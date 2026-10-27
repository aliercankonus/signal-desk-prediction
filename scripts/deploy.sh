#!/usr/bin/env bash
# Run on the Docker host. Preserve active config and persistent volumes.
set -Eeuo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
project=signal-desk-prediction
port=""
bind=""
smoke=1
initialize=0
expected_host=""
while (($#)); do
  case "$1" in
    --project) project="${2:?missing project}"; shift 2 ;;
    --port) port="${2:?missing port}"; shift 2 ;;
    --bind) bind="${2:?missing bind}"; shift 2 ;;
    --expected-host) expected_host="${2:?missing hostname}"; shift 2 ;;
    --no-smoke) smoke=0; shift ;;
    --initialize-config) initialize=1; shift ;;
    -h|--help) echo "usage: bash scripts/deploy.sh [--project NAME] [--port PORT] [--bind 127.0.0.1|0.0.0.0] [--expected-host HOST] [--no-smoke]"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
die() { echo "ERROR: $*" >&2; exit 1; }
[[ "$project" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die "Invalid Compose project name"
command -v systemd-detect-virt >/dev/null || die "Cannot verify host context; run on a supported Linux host"
if systemd-detect-virt --container --quiet; then
  die "Run on the Docker host, not inside an agent container"
fi
[[ -z "$expected_host" || "$(hostname)" == "$expected_host" ]] || die "Hostname does not match --expected-host"
command -v docker >/dev/null || die "Docker is missing; use install.sh --install-docker on a fresh Ubuntu host"
docker info >/dev/null || die "Docker daemon unavailable; host access is required"
docker compose version >/dev/null || die "Docker Compose plugin missing"
docker buildx version >/dev/null || die "Docker Buildx plugin missing"
docker compose up --help | grep -q -- '--wait-timeout' || die "Compose must support up --wait and --wait-timeout"
command -v git >/dev/null || die "git is required"
[[ -d "$repo_dir/.git" ]] || die "Deployment requires a Git checkout"
git_here() { git -c "safe.directory=$repo_dir" -C "$repo_dir" "$@"; }
git_here diff --quiet HEAD -- . ':(exclude)config/config.yaml' || die "Tracked code changes exist; commit or review them first"
if [[ -n "$(docker ps --filter "label=com.docker.compose.project=$project" --filter label=com.docker.compose.service=collector --format '{{.ID}}')" ]]; then
  die "A collector is running in this project; stop it deliberately before deployment"
fi
free_kib=$(df -Pk "$repo_dir" | awk 'NR==2 {print $4}')
[[ "$free_kib" =~ ^[0-9]+$ && "$free_kib" -ge 10485760 ]] || die "At least 10 GiB free is required for bootstrap"
memory_kib=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
[[ "$memory_kib" =~ ^[0-9]+$ && "$memory_kib" -ge 1572864 ]] || die "Host is below the 2 GB class resource profile"

cd "$repo_dir"
mkdir -p runtime/install
run_dir=$(mktemp -d "$repo_dir/runtime/install/run.XXXXXXXX")
exec > >(tee -a "$run_dir/deploy.log") 2>&1
stage=prepare
trap 'rc=$?; echo "DEPLOY_FAILED stage=$stage exit=$rc log=$run_dir/deploy.log"; exit "$rc"' ERR
run() { printf '+ '; printf '%q ' "$@"; printf '\n'; "$@"; }
compose() { docker compose -p "$project" -f "$repo_dir/docker-compose.yml" "$@"; }
echo "Deployment started: $(date -u +%FT%TZ)"
commit=$(git_here rev-parse HEAD)
printf '%s\n' "$commit" > "$run_dir/git-commit.txt"
echo "Commit: $commit"
env_created=0
if [[ ! -f .env ]]; then cp .env.example .env; env_created=1; fi
mkdir -p config
if [[ ! -f config/config.yaml ]]; then
  cp config/config.example.yaml config/config.yaml
elif ((initialize)) && git_here diff --quiet HEAD -- config/config.yaml; then
  # New clone's tracked sample is not a user's active configuration.
  cp config/config.example.yaml config/config.yaml
fi

read_key() {
  local key="$1"
  local found
  found=$(grep -E "^$key=" .env || true)
  [[ -z "$found" || "$(printf '%s\n' "$found" | wc -l)" -eq 1 ]] || die "Duplicate $key in .env"
  printf '%s' "${found#*=}"
}
save_key() {
  local key="$1" value="$2" old
  old=$(read_key "$key")
  if grep -qE "^$key=" .env; then
    if ((env_created)); then
      sed -i "s/^$key=.*/$key=$value/" .env
    else
      [[ "$old" == "$value" ]] || die "$key differs in .env; choose matching flags or deliberately edit it"
    fi
  else
    printf '\n%s=%s\n' "$key" "$value" >> .env
  fi
}
port="${port:-$(read_key SDP_API_PORT)}"
bind="${bind:-$(read_key SDP_BIND_ADDRESS)}"
port="${port:-8080}"
bind="${bind:-127.0.0.1}"
[[ "$port" =~ ^[0-9]{1,5}$ ]] || die "Port must be numeric"
port=$((10#$port))
((port >= 1 && port <= 65535)) || die "Port out of range"
[[ "$bind" == 127.0.0.1 || "$bind" == 0.0.0.0 ]] || die "Unsupported bind address"
save_key COMPOSE_PROJECT_NAME "$project"
save_key SDP_API_PORT "$port"
save_key SDP_BIND_ADDRESS "$bind"
export SDP_API_PORT="$port" SDP_BIND_ADDRESS="$bind"
chmod 600 .env
# Never print .env contents. Keep the active config fingerprint locally.
sha256sum config/config.yaml > "$run_dir/config.sha256"
previous=$(compose ps -q api)
if [[ -n "$previous" ]]; then
  docker inspect "$previous" --format '{{.Image}}' > "$run_dir/previous-api-image.txt"
fi

stage=compose
run compose config -q
stage=build
run compose build api collector
stage=config
run compose run --rm --no-deps collector python -m signal_desk.tools.validate_all --config config/config.yaml
stage=tests
run compose run --rm --no-deps collector python -m pytest -q
if ((smoke)); then
  stage=snapshot
  run compose run --rm --no-deps collector python -u -m signal_desk.collector.binance_collector --mode once --config config/config.yaml
  stage=stream
  run compose run --rm --no-deps collector python -u -m signal_desk.collector.binance_collector --mode stream --max-events 25 --config config/config.yaml
fi
stage=api
run compose up -d --no-deps --wait --wait-timeout 90 api
stage=health
run compose exec -T api python -m signal_desk.tools.install_check --health-url http://127.0.0.1:8080/health
stage=manifest
api_container=$(compose ps -q api)
api_image=$(docker inspect "$api_container" --format '{{.Image}}')
collector_image=$(docker image inspect "$project-collector" --format '{{.Id}}')
compose run --rm --no-deps collector python -m signal_desk.tools.install_check \
  --config config/config.yaml --git-commit "$commit" --project "$project" \
  --smoke "$smoke" --api-image "$api_image" --collector-image "$collector_image" > "$run_dir/manifest.json.tmp"
mv "$run_dir/manifest.json.tmp" "$run_dir/manifest.json"
stage=complete
echo "DEPLOY_OK project=$project paper_only=true collector=idle smoke=$smoke"
echo "Local manifest: $run_dir/manifest.json"
echo "Local command log: $run_dir/deploy.log"

