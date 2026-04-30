format:
	uv run ruff format .

lint:
	uv run ruff check .

typecheck:
	uv run pyright

test:
	uv run pytest -m "not integration"

test-integration:
	uv run pytest -m integration

test-all: test test-integration

quality: format lint typecheck test-all

ci branch=`git branch --show-current`:
	gh workflow run CI --ref "{{branch}}"
