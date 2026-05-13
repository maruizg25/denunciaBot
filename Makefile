# =============================================================================
# DenunciaBot — Makefile de desarrollo
# -----------------------------------------------------------------------------
# Atajos para los comandos más usados. Requiere bash o zsh.
# Ejecutar siempre desde la raíz del proyecto:
#   make help
# =============================================================================

.PHONY: help venv install install-dev up down logs migrate migrate-down \
        init-db run worker test test-cov lint format clean export

# Detecta python3.11 (preferido) o python3 como fallback
PYTHON := $(shell command -v python3.11 2>/dev/null || command -v python3)
VENV := .venv
BIN := $(VENV)/bin

help:  ## Lista los comandos disponibles
	@echo "Comandos disponibles:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---- Entorno virtual --------------------------------------------------------

venv:  ## Crea el entorno virtual (.venv)
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	@echo "Entorno creado. Activar con: source $(VENV)/bin/activate"

install: venv  ## Instala dependencias de producción
	$(BIN)/pip install -r requirements.txt

install-dev: install  ## Instala deps + herramientas de desarrollo
	$(BIN)/pip install pytest pytest-asyncio pytest-cov httpx faker ruff mypy

# ---- Servicios externos (Docker) --------------------------------------------

up:  ## Levanta PostgreSQL + Redis con docker-compose
	docker compose up -d
	@echo "Esperando a que los servicios estén saludables..."
	@sleep 3
	@docker compose ps

down:  ## Detiene los servicios (preserva datos)
	docker compose down

down-clean:  ## Detiene y BORRA todos los datos (CUIDADO)
	@read -p "¿Borrar TODOS los datos? Escribe 'si' para confirmar: " confirm && \
		[ "$$confirm" = "si" ] && docker compose down -v || echo "Cancelado."

logs:  ## Sigue los logs de postgres y redis
	docker compose logs -f

# ---- Base de datos ----------------------------------------------------------

init-db:  ## Inicializa la BD (verifica + migra + valida triggers)
	$(BIN)/python scripts/init_db.py

migrate:  ## Aplica migraciones pendientes
	$(BIN)/alembic upgrade head

migrate-down:  ## Reversa una migración
	$(BIN)/alembic downgrade -1

migrate-new:  ## Crea una nueva migración (MSG="descripción")
	@if [ -z "$(MSG)" ]; then echo "Uso: make migrate-new MSG='descripcion del cambio'"; exit 1; fi
	$(BIN)/alembic revision --autogenerate -m "$(MSG)"

# ---- Ejecución --------------------------------------------------------------

run:  ## Levanta el API en modo desarrollo (con reload)
	$(BIN)/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

run-prod:  ## Levanta el API en modo producción local (gunicorn)
	$(BIN)/gunicorn app.main:app \
		-w 2 -k uvicorn.workers.UvicornWorker \
		-b 127.0.0.1:8000 --access-logfile - --error-logfile -

worker:  ## Levanta el worker Dramatiq (en otra terminal)
	$(BIN)/dramatiq app.services.notificacion_service \
		--processes 1 --threads 2 --queues notificaciones cierres

# ---- Tests y calidad --------------------------------------------------------

test:  ## Corre los tests unitarios (excluye integración)
	$(BIN)/pytest

test-integration:  ## Tests de integración (requiere `make up` + `make init-db`)
	$(BIN)/pytest -m integration --override-ini="addopts=--strict-markers --tb=short -ra"

test-all:  ## Todos los tests (unitarios + integración)
	$(BIN)/pytest --override-ini="addopts=--strict-markers --tb=short -ra"

test-cov:  ## Tests unitarios con reporte de cobertura
	$(BIN)/pytest --cov=app --cov-report=term-missing --cov-report=html
	@echo "Reporte HTML: htmlcov/index.html"

test-fast:  ## Tests excluyendo los marcados como slow o integration
	$(BIN)/pytest -m "not slow and not integration"

lint:  ## Ejecuta ruff (linter)
	$(BIN)/ruff check app tests scripts

format:  ## Formatea el código con ruff
	$(BIN)/ruff format app tests scripts

typecheck:  ## Verifica tipos con mypy
	$(BIN)/mypy app

# ---- Utilidades -------------------------------------------------------------

export:  ## Exporta alertas a CSV (FILE=ruta.csv para personalizar)
	$(BIN)/python scripts/export_alertas.py --salida $${FILE:-alertas.csv}

backup:  ## Hace backup de la BD a /tmp (DEST=ruta para cambiar destino)
	$(BIN)/python scripts/backup_db.py --destino $${DEST:-/tmp/denunciabot-backups}

clean-tmp:  ## Borra archivos temporales de evidencias huérfanas (>30 min)
	$(BIN)/python scripts/limpiar_temporales.py --verbose

clean:  ## Limpia caches y archivos temporales
	find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.pytest_cache' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.mypy_cache' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.ruff_cache' -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov .coverage build dist *.egg-info
