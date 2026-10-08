# Build, run and stress-test the three services.
# Usage: make help

COMPOSE := docker compose
PY      := .venv/bin/python
A_URL   ?= http://localhost:8081
B_URL   ?= http://localhost:8082
C_URL   ?= http://localhost:8083

# stress knobs: make stress IPS=60 CONCURRENCY=20
IPS         ?= 30
CONCURRENCY ?= 10
LIST_SIZE   ?= 5

.PHONY: help venv build up down restart ps logs logs-c wait unit stress providers clusters verify clean

help:
	@echo "make venv      - create .venv from requirements.txt + pytest, pytest-asyncio"
	@echo "make build     - build the three docker images"
	@echo "make up        - build, start detached, wait until all services answer"
	@echo "make down      - stop and remove the containers and network"
	@echo "make restart   - down + up"
	@echo "make unit      - run the pytest suites (no docker needed)"
	@echo "make stress    - run the API stress test against the running stack"
	@echo "make providers - count provider failovers in Service C's logs"
	@echo "make clusters  - pretty-print /generate-geo-clusters"
	@echo "make verify    - venv + build + up + unit + stress"
	@echo "make logs      - follow all logs    (make logs-c = Service C only)"
	@echo "make clean     - down, drop volumes, remove caches and .venv"

venv: .venv/bin/python

.venv/bin/python:
	python3 -m venv .venv
	.venv/bin/pip install --quiet --upgrade pip
	.venv/bin/pip install --quiet -r requirements.txt pytest pytest-asyncio

build:
	$(COMPOSE) build

up: build
	$(COMPOSE) up -d
	@$(MAKE) --no-print-directory wait

down:
	$(COMPOSE) down

restart: down up

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

logs-c:
	$(COMPOSE) logs -f service-c-container

# poll until every service serves its OpenAPI schema
wait:
	@printf "waiting for services"
	@for i in $$(seq 1 60); do \
		if curl -fsS $(A_URL)/openapi.json >/dev/null 2>&1 \
		&& curl -fsS $(B_URL)/openapi.json >/dev/null 2>&1 \
		&& curl -fsS $(C_URL)/openapi.json >/dev/null 2>&1; then \
			echo " ok"; exit 0; fi; \
		printf "."; sleep 1; \
	done; \
	echo " FAILED"; $(COMPOSE) ps; exit 1

unit: venv
	$(PY) -m pytest tests -q

stress: venv
	$(PY) scripts/stress_test.py --ips $(IPS) --concurrency $(CONCURRENCY) \
		--list-size $(LIST_SIZE) \
		--service-a $(A_URL) --service-b $(B_URL) --service-c $(C_URL) $(STRESS_ARGS)

# how often each provider was skipped or failed over during the last run
providers:
	@echo "provider failovers logged by Service C:"
	@$(COMPOSE) logs service-c-container 2>/dev/null \
		| grep -oE "Error with GeoAPIProvider[0-9]+" | sort | uniq -c || echo "  none"
	@echo "rate-limit headers seen from ip-api (X-Rl = requests left):"
	@$(COMPOSE) logs service-c-container 2>/dev/null | grep -oE "X-Rl: [0-9]+" | tail -5 || true

clusters:
	@curl -fsS "$(B_URL)/generate-geo-clusters" | $(PY) -m json.tool | head -60

verify: up unit stress

clean: down
	$(COMPOSE) down -v --remove-orphans
	rm -rf .venv .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
