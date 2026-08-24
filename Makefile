.DEFAULT_GOAL := help

.PHONY: help up load incremental quality inspect demo-failure demo-recovery test lint reset clean

COMPOSE := docker compose
RUN := $(COMPOSE) run --rm pipeline

help: ## List available commands
	@awk 'BEGIN {FS = ":.*## "; printf "Fundo take-home commands:\n"} /^[a-zA-Z_-]+:.*?## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

up: ## Build, seed, run the initial load, and validate quality
	$(COMPOSE) up --build --abort-on-container-exit --exit-code-from pipeline

load: ## Run an idempotent incremental load and quality checks
	$(RUN) run --quality

incremental: ## Apply a repeatable source change-set, then load only changes
	$(RUN) mutate-source
	$(RUN) run --quality

quality: ## Compare current source and warehouse state
	$(RUN) quality

inspect: ## Print warehouse row counts, last run, metrics, and DQ results
	$(RUN) inspect

demo-failure: ## Corrupt the warehouse temporarily and prove a check catches it
	$(RUN) demo-failure

demo-recovery: ## Inject a mid-run crash and prove rollback plus safe replay
	$(RUN) demo-recovery

test: ## Run the automated unit and integration test suite
	$(COMPOSE) run --rm --entrypoint pytest pipeline -q

lint: ## Run lightweight static checks
	$(COMPOSE) run --rm --entrypoint python pipeline -m compileall -q src tests

reset: ## Remove local containers and data volumes (destructive, local only)
	$(COMPOSE) down --volumes --remove-orphans

clean: reset ## Alias for reset

