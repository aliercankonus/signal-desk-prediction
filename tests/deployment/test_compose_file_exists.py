from pathlib import Path


def test_deployment_files_exist():
    for path in ["docker-compose.yml", "Dockerfile", ".env.example", "scripts/bootstrap.sh", "scripts/preflight.sh"]:
        assert Path(path).exists(), path
