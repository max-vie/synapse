.PHONY: help setup demo check test validate lab-up configure lab-down lab-status lab-logs proof \
	mocked-fastapi-qdrant-e2e ci-e2e real-local-stack-proof clean remove \
	public-hygiene scan-removed-publisher doc-links update-check start-synapse

PYTHON ?= python3
.DEFAULT_GOAL := help

help:
	@printf '%s\n' \
		"Synapse commands:" \
		"  make lab-up      Start/import the local lab services" \
		"  make start-synapse Start Synapse service after infra + collection setup" \
		"  make configure   Check manual Wiki.js API/token setup" \
		"  make proof       Run the live lab proof after configure" \
		"  make demo        Run the no-network reviewer demo" \
		"  make check       Run local release checks" \
		"  make test        Run tests" \
		"  make validate    Validate generated workflows and public safety" \
		"  make lab-down    Stop the local lab without deleting data" \
		"  make lab-status  Show lab service status" \
		"  make lab-logs    Show lab service logs" \
		"  make mocked-fastapi-qdrant-e2e Run mocked FastAPI/Qdrant plumbing proof" \
		"  make real-local-stack-proof Run manual real Ollama/Wiki.js/Qdrant proof" \
		"  make update-check Check reviewed Docker image pins" \
		"  make remove     Remove all lab containers, volumes, .env, and local artifacts" \
		"  make clean       Remove local benchmark output"

setup:
	@printf '%s\n' "Compatibility alias. Use the explicit flow: make lab-up, make configure, make proof."
	$(MAKE) lab-up

demo:
	$(PYTHON) scripts/demo.py

check: test validate public-hygiene scan-removed-publisher doc-links

test:
	$(PYTHON) -m pytest -q

validate:
	$(PYTHON) scripts/validate.py .

lab-up:
	@echo "==> Setting up .env and generating secrets ..."
	scripts/e2e/setup.sh
	@echo "==> Starting infrastructure services (qdrant, ollama, wikijs) ..."
	scripts/e2e/start.sh
	@echo "==> Pulling Ollama models ..."
	scripts/e2e/pull-models.sh
	@echo "==> Creating Qdrant collection (derives name from OLLAMA_EMBED_MODEL dimension) ..."
	scripts/e2e/create-qdrant-collection.sh
	@echo "==> Starting Synapse service (reads updated QDRANT_COLLECTION from .env) ..."
	scripts/e2e/start-synapse.sh

lab-down:
	scripts/e2e/stop.sh

lab-status:
	scripts/e2e/status.sh

lab-logs:
	scripts/e2e/logs.sh

configure:
	scripts/e2e/configure.sh

proof: configure
	scripts/e2e/local-e2e-proof.sh

mocked-fastapi-qdrant-e2e:
	scripts/e2e/ci-e2e.sh

ci-e2e: mocked-fastapi-qdrant-e2e

real-local-stack-proof:
	scripts/e2e/real-local-stack-proof.sh

clean:
	rm -rf .local-artifacts/benchmarks

remove:
	scripts/e2e/remove.sh

public-hygiene:
	$(PYTHON) scripts/public_hygiene.py .

scan-removed-publisher:
	$(PYTHON) scripts/check_removed_publisher.py .

doc-links:
	$(PYTHON) scripts/check_docs_links.py .

update-check:
	$(PYTHON) scripts/check_image_versions.py --format text

start-synapse:
	scripts/e2e/start-synapse.sh
