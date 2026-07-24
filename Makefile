SHELL := /bin/sh
COMPOSE := docker compose

.PHONY: up down restart logs ps build test lint migrate health backup probe-sources

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

build:
	$(COMPOSE) build --pull

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

test:
	$(COMPOSE) exec -T api pytest
	$(COMPOSE) exec -T web npm run test -- --run

lint:
	$(COMPOSE) exec -T api ruff check app
	$(COMPOSE) exec -T web npm run lint

migrate:
	$(COMPOSE) exec -T api alembic upgrade head

health:
	curl -fsS http://localhost:8000/health
	curl -fsS http://localhost:3000/login >/dev/null

backup:
	$(COMPOSE) exec -T postgres pg_dump -U convocaradar -d convocaradar > backups/manual-$$(date -u +%Y%m%dT%H%M%SZ).sql

probe-sources:
	 exec -T api python /tmp/probe_source_contracts.py

