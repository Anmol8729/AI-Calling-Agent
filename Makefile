.PHONY: help install dev-backend dev-frontend dev-agent test lint build migrate docker-up docker-down

help:
	@echo "Clarivo — Production AI Calling & Practice Management Platform"
	@echo ""
	@echo "Usage:"
	@echo "  make install       Install backend, agent, and frontend dependencies"
	@echo "  make dev-backend   Run FastAPI backend server with reload"
	@echo "  make dev-frontend  Run Vite frontend dev server"
	@echo "  make dev-agent     Run LiveKit voice AI agent worker"
	@echo "  make test          Run backend pytest suite"
	@echo "  make lint          Run Ruff linter on backend and agent"
	@echo "  make build         Build frontend production bundle"
	@echo "  make migrate       Apply Alembic database migrations"
	@echo "  make docker-up     Start all services via Docker Compose"
	@echo "  make docker-down   Stop all Docker Compose services"

install:
	pip install -r backend/requirements.txt -r agent/requirements.txt
	npm --prefix frontend ci

dev-backend:
	uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload

dev-frontend:
	npm --prefix frontend run dev

dev-agent:
	python agent/main.py dev

test:
	pytest backend/tests -v

lint:
	ruff check backend agent

build:
	npm --prefix frontend run build

migrate:
	alembic upgrade head

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down
