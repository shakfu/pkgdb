
PHONY: all sync update fetch report clean reseat


all: sync


sync:
	@uv run sync


update:
	@uv run pkglog update


fetch:
	@uv run pkglog fetch


report:
	@uv run pkglog report


clean:
	@rm -f report.html


reset: clean
	@rm -rf build dist .venv
