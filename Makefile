SHELL := /bin/bash

IMAGE       ?= sceance
TAG         ?= test
CONTAINER   ?= sceance-local
PORT        ?= 8080
ENV_FILE    ?= server/.env

.DEFAULT_GOAL := help

.PHONY: help build run sh logs stop rm restart push test test-health clean prune

help: ## Show available make targets.
	@echo "Available make targets:"
	@grep -E '^[a-zA-Z0-9_-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}{printf "  %-14s %s\n", $$1, $$2}'

# ---- Docker ---------------------------------------------------------

build: ## Build the App Platform image locally.
	docker build -t $(IMAGE):$(TAG) .

run: ## Run the image locally with .env, personas and static/ mounted, port $(PORT) exposed.
	docker run --rm -d \
		--name $(CONTAINER) \
		--env-file $(ENV_FILE) \
		-v "$(CURDIR)/personas:/app/personas:ro" \
		-v "$(CURDIR)/server/static:/app/server/static:ro" \
		-p $(PORT):8080 \
		$(IMAGE):$(TAG)
	@echo "running at http://localhost:$(PORT)"

sh: ## Open an interactive shell inside the running container.
	docker exec -it $(CONTAINER) /bin/bash

logs: ## Tail logs from the running container.
	docker logs -f $(CONTAINER)

stop: ## Stop the running container.
	-docker stop $(CONTAINER)

rm: ## Remove the stopped container (rarely needed; run uses --rm).
	-docker rm $(CONTAINER)

restart: stop run ## Restart: stop the container then run it again.

test-health: ## Hit /health on the running container; waits up to 30s for startup.
	@for i in $$(seq 1 30); do \
		if curl -fsS http://localhost:$(PORT)/health 2>/dev/null; then \
			echo ""; exit 0; \
		fi; sleep 1; \
	done; echo "health check FAILED after 30s"; exit 1

clean: ## Remove the locally built image.
	-docker rmi $(IMAGE):$(TAG)

prune: ## Reclaim disk: drop dangling (<none>) images + build cache. Keeps tagged images, containers, volumes.
	@echo "Before:"; docker system df
	docker image prune -f
	docker builder prune -f
	@echo "After:"; docker system df

# ---- Push to GitHub (triggers App Platform deploy) -----------------

push: ## Push current branch to origin (triggers App Platform redeploy on main).
	git push origin $$(git rev-parse --abbrev-ref HEAD)

test: ## Run Python unit tests.
	cd server && uv run pytest
