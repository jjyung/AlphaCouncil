.PHONY: sync lock run web api-server k8000

sync:
	uv sync

lock:
	uv lock

run:
	uv run adk run alpha_council

web:
	uv run adk web

api-server:
	uv run adk api_server

k8000:
	@pids="$$(lsof -ti :8000)"; \
	if [ -n "$$pids" ]; then \
		kill -9 $$pids; \
		echo "Killed process(es) on :8000 -> $$pids"; \
	else \
		echo "No process is listening on :8000"; \
	fi
