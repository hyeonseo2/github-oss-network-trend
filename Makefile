SHELL := /bin/bash

.PHONY: help build-data run-site clean-data

help:
	@echo "Open Source Ecosystem Analytics - Site helpers"
	@echo "  make help             Show available tasks in this project"
	@echo "  make build-data       Build docs/data/*.json from GitHub API"
	@echo "  make run-site         Run local site on :8080"
	@echo "  make clean-data       Remove generated JSON files"

build-data:
	python3 scripts/build_data.py --output docs/data

run-site:
	python3 -m http.server 8080 -d docs

clean-data:
	find docs/data -maxdepth 1 -type f -name '*.json' -delete
