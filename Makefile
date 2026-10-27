PYTHONPATH := src
CONFIG ?= config/config.example.yaml

.PHONY: test validate bootstrap snapshot-smoke stream-smoke eod docker-config

test:
	PYTHONPATH=$(PYTHONPATH) python -m pytest -q

validate:
	PYTHONPATH=$(PYTHONPATH) python -m signal_desk.tools.validate_all --config $(CONFIG)

bootstrap:
	PYTHONPATH=$(PYTHONPATH) ./scripts/bootstrap.sh

snapshot-smoke:
	PYTHONPATH=$(PYTHONPATH) ./scripts/binance_snapshot_smoke.sh $(CONFIG)

stream-smoke:
	PYTHONPATH=$(PYTHONPATH) ./scripts/binance_stream_smoke.sh $(CONFIG)

docker-config:
	docker compose config -q
