.PHONY: install inspect test quality format

install:
	uv sync
	uv run nbstripout --install

inspect:
	uv run python -m xray.data

test:
	uv run pytest -q

quality:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .
