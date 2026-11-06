.PHONY: env up down psql setup ingest lint fmt test

RAW_FILE := data/raw/EmendasParlamentares.csv

env:
	@test -f .env || cp .env.example .env

up: env
	docker compose up -d --wait

down:
	docker compose down

setup: up
	uv sync

$(RAW_FILE):
	uv run python scripts/download_federal.py

ingest: up $(RAW_FILE)
	uv run rastro ingest

psql: env
	docker compose exec db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

lint:
	uv run ruff check
	uv run ruff format --check

fmt:
	uv run ruff check --fix
	uv run ruff format

test:
	uv run pytest
