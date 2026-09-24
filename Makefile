.PHONY: install fmt lint typecheck test test-integration emulator-up emulator-down check

install:
	uv sync

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run pyright

test:
	uv run pytest

test-integration:
	uv run pytest -m integration

emulator-up:
	docker run -d --rm --name wenchang-fake-gcs -p 4443:4443 fsouza/fake-gcs-server -scheme http -port 4443

emulator-down:
	docker stop wenchang-fake-gcs

check: lint typecheck test
