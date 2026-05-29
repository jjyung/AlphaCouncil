.PHONY: sync lock run run-cli web api-server k8000

## Install and sync Python dependencies via uv.
sync:
	uv sync

## Refresh uv lockfile from current dependency graph.
lock:
	uv lock

## Run ADK CLI flow for alpha_council agent.
run:
	uv run adk run alpha_council

## Run one full pipeline execution with local env overlays.
run-cli:
	@if [ -f .env ]; then set -a; . ./.env; set +a; fi; \
	if [ -f alpha_council/.env ]; then set -a; . ./alpha_council/.env; set +a; fi; \
	uv run alpha-council run --ticker 2330 --market tw --masters 1,2,3

## Launch ADK Web UI for local debugging.
web:
	uv run adk web

## Launch ADK API server locally.
api-server:
	uv run adk api_server

## Kill local processes listening on port 8000.
k8000:
	@pids="$$(lsof -ti :8000)"; \
	if [ -n "$$pids" ]; then \
		kill -9 $$pids; \
		echo "Killed process(es) on :8000 -> $$pids"; \
	else \
		echo "No process is listening on :8000"; \
	fi
