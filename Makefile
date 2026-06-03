# ==============================================================================
# MTO Treasury System — Developer Task Runner
# ==============================================================================

# OS Detection and Path Configuration
ifeq ($(OS),Windows_NT)
    PYTHON  = venv\Scripts\python.exe
    PIP     = venv\Scripts\pip.exe
    ALEMBIC = venv\Scripts\alembic.exe
else
    PYTHON  = venv/bin/python
    PIP     = venv/bin/pip
    ALEMBIC = venv/bin/alembic
endif

.PHONY: help install dev test lint format migrate

help:
	@echo "MTO Treasury System Management Commands:"
	@echo "  make install  - Install requirements and development dependencies"
	@echo "  make dev      - Start the local FastAPI backend server"
	@echo "  make test     - Run the pytest test suite"
	@echo "  make lint     - Run flake8, black, isort, and bandit checks"
	@echo "  make format   - Format the codebase using black and isort"
	@echo "  make migrate  - Run database migrations (Alembic upgrade head)"

install:
	$(PIP) install -r requirements.txt -r dev-requirements.txt

dev:
	$(PYTHON) backend/main.py

test:
	$(PYTHON) run_tests.py

lint:
	$(PYTHON) -m flake8 backend/
	$(PYTHON) -m black --check backend/
	$(PYTHON) -m isort --check backend/
	$(PYTHON) -m bandit -r backend/

format:
	$(PYTHON) -m black backend/
	$(PYTHON) -m isort backend/

migrate:
	$(ALEMBIC) upgrade head
