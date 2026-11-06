.PHONY: env up down psql lint fmt test

env:
	@test -f .env || cp .env.example .env

up: env
	docker compose up -d --wait

down:
	docker compose down

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
