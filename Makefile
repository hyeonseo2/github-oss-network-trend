SHELL := /bin/bash

.PHONY: help lint test-dashboard run-dashboard run-dbt test-dbt test-pipeline clean

help:
	@echo "Open Source Ecosystem Analytics - Capstone helpers"
	@echo "  make help             Show available tasks in this project"
	@echo "  make lint             Check Python syntax (py_compile)"
	@echo "  make run-dashboard    Run local Flask app"
	@echo "  make test-dashboard    Health check dashboard endpoint"
	@echo "  make run-dbt          Run dbt locally (prod target)"
	@echo "  make test-dbt          dbt test"

lint:
	python -m py_compile app/main.py

run-dashboard:
	python -m pip install -r requirements-web.txt
	cd app && python main.py

test-dashboard:
	curl -sf http://127.0.0.1:8080/ >/tmp/oss_dashboard_check.html || exit 1
	rm -f /tmp/oss_dashboard_check.html

run-dbt:
	cd dbt && \
	dbt run --project-dir . --profiles-dir . --target prod \
	  --vars '{"gcp_project_id":"$${GCP_PROJECT_ID}","raw_dataset":"${RAW_DATASET:-oss_analytics_raw}","raw_table":"${RAW_TABLE:-raw_github_events}","analysis_window_days":30,"network_window_days":30,"min_daily_events_for_trend":5}'

test-dbt:
	cd dbt && \
	dbt test --project-dir . --profiles-dir . --target prod \
	  --vars '{"gcp_project_id":"$${GCP_PROJECT_ID}","raw_dataset":"${RAW_DATASET:-oss_analytics_raw}","raw_table":"${RAW_TABLE:-raw_github_events}"}'

test-pipeline:
	make run-dbt
	make test-dbt

clean:
	rm -rf dbt/target dbt/logs .pytest_cache .mypy_cache app/__pycache__
