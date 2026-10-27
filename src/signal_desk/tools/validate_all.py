from __future__ import annotations

import argparse
import sys
from pathlib import Path

from signal_desk.config.loader import validate_config
from signal_desk.schemas.validate import validate_all_schemas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--schema", default="schemas/config.schema.json")
    parser.add_argument("--schema-dir", default="schemas")
    args = parser.parse_args(argv)
    checked = validate_all_schemas(args.schema_dir)
    config = validate_config(args.config, args.schema)
    print(f"schemas_ok={len(checked)} config_version={config['project']['config_version']} mode={config['project']['mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
