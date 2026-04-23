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
	kill -9 $(lsof -ti :8000)
