
PHONY: all sync update fetch report clean reseat


all: sync


sync:
	@uv run sync


update:
	@uv run pkglog.py update


fetch:
	@uv run pkglog.py fetch


report:
	@uv run pkglog.py report


clean:
	@rm -f report.html


reset: clean
	@rm -rf build dist .venv
