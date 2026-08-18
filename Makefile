.PHONY: help demo evaluate install check test lab-up configure lab-down lab-status lab-logs proof \
	mocked-fastapi-qdrant-e2e real-local-stack-proof clean remove update-check start-synapse

PYTHON ?= python3
.DEFAULT_GOAL := help

help:
	@printf '%s\n' \
		"Synapse commands:" \
		"  make lab-up      Start and prepare the local lab services" \
		"  make start-synapse Start Synapse service after infra + collection setup" \
		"  make configure   Check manual Wiki.js API/token setup" \
		"  make proof       Run the live lab proof after configure" \
		"  make demo        Run the no-network reviewer demo" \
		"  make evaluate    Run the no-network source-grounded AI evaluation" \
		"  make check       Run local release checks" \
		"  make test        Run tests" \
		"  make lab-down    Stop the local lab without deleting data" \
		"  make lab-status  Show lab service status" \
		"  make lab-logs    Show lab service logs" \
		"  make mocked-fastapi-qdrant-e2e Run mocked FastAPI/Qdrant plumbing proof" \
		"  make real-local-stack-proof Run manual real Ollama/Wiki.js/Qdrant proof" \
		"  make update-check Check reviewed Docker image pins" \
		"  make remove     Remove all lab containers, volumes, .env, and local artifacts" \
		"  make clean       Remove local benchmark output"

demo:
	$(PYTHON) scripts/demo.py

evaluate:
	$(PYTHON) -m scripts.evaluate

install:
	$(PYTHON) -m pip install -e ".[dev]"

check: install test
	$(PYTHON) -m scripts.checks all

test: install
	$(PYTHON) -m pytest -q

lab-up:
	$(PYTHON) -m scripts.lab up

lab-down:
	$(PYTHON) -m scripts.lab down

lab-status:
	$(PYTHON) -m scripts.lab status

lab-logs:
	$(PYTHON) -m scripts.lab logs

configure:
	$(PYTHON) -m scripts.lab configure

proof:
	$(PYTHON) -m scripts.lab proof

mocked-fastapi-qdrant-e2e:
	$(PYTHON) -m scripts.lab mocked-proof

real-local-stack-proof:
	$(PYTHON) -m scripts.lab real-proof

clean:
	rm -rf .local-artifacts/benchmarks

remove:
	$(PYTHON) -m scripts.lab remove

update-check:
	$(PYTHON) -m scripts.checks images --format text

start-synapse:
	$(PYTHON) -m scripts.lab start-service
