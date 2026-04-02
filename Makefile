NAME := pkgdb

.PHONY: all test coverage sync update fetch report lint typecheck format qa \
		build wheel sdist check publish publish-test clean reset \
		docs docs-serve docs-deploy

all: test

sync:
	@uv sync

test: sync
	@uv run pytest

coverage: sync
	@uv run pytest --cov=pkgdb --cov-report=term-missing --cov-report=html

update:
	@uv run $(NAME) update

fetch:
	@uv run $(NAME) fetch

report:
	@uv run $(NAME) report

lint:
	@uv run ruff check --fix src/

typecheck:
	@uv run mypy --strict src/

format:
	@uv run ruff format src/

qa: test lint typecheck format

build: clean
	@uv build
	@uv run twine check dist/*

wheel: clean
	@uv build --wheel
	@uv run twine check dist/*

sdist: clean
	@uv build --sdist

check: build
	@uv run twine check dist/*

publish: check
	@uv run twine upload dist/*

publish-test: check
	@uv run twine upload --repository testpypi dist/*

docs:
	@uv run --group docs mkdocs build

docs-serve:
	@uv run --group docs mkdocs serve

docs-deploy:
	@uv run --group docs mkdocs gh-deploy --force

clean:
	@rm -f report.html
	@rm -rf site/

reset: clean
	@rm -rf build dist .venv *.egg-info src/*.egg-info htmlcov .coverage
