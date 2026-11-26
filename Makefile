export COMPOSE_PROJECT_NAME ?= human-models-mcp-night
export HMM_UID ?= $(shell id -u)
export HMM_GID ?= $(shell id -g)
export BUILDX_CONFIG := $(CURDIR)/.cache/buildx
DC = docker compose -p $(COMPOSE_PROJECT_NAME)
RUN = $(DC) run --rm --no-deps -T

.PHONY: provision doctor build test e2e demo release-check gpu-smoke client stdio package clean-check experiment agent-check contact-negative
provision:
	python3 scripts/provision.py

doctor:
	python3 scripts/doctor.py

build: provision
	mkdir -p results reports/logs render_jobs
	python3 -m venv .client-venv
	.client-venv/bin/python -m pip --disable-pip-version-check install --no-cache-dir --require-hashes -r requirements.lock
	$(DC) build runtime

test:
	$(RUN) --entrypoint sh runtime -c 'ruff check --no-cache src tests scripts examples && pytest -q -p no:cacheprovider && python scripts/check_package.py'

e2e:
	$(RUN) --entrypoint python runtime scripts/e2e.py
	python3 scripts/fresh_clients.py

demo: render-preview

client:
	$(RUN) --entrypoint python runtime examples/mcp-client/client.py

stdio:
	$(RUN) runtime

gpu-smoke:
	python3 scripts/gpu_smoke.py

release-check:
	python3 scripts/public_check.py

package:
	python3 scripts/package_release.py

clean-check:
	python3 scripts/clean_check.py

experiment:
	python3 scripts/experiment.py

agent-check:
	python3 scripts/verify_agent.py

contact-negative:
	$(RUN) --entrypoint python runtime scripts/contact_negative.py

.PHONY: render-build render-start render-gpu-start render-preview render-e2e render-gpu-smoke
render-build: build
	python3 scripts/provision_renderer.py
	$(DC) build renderer

render-start:
	mkdir -p results render_jobs
	$(DC) up -d --no-deps renderer

render-gpu-start:
	mkdir -p results render_jobs
	$(DC) -f compose.yaml -f compose.render-gpu.yaml up -d --no-deps renderer

render-preview:
	python3 scripts/render_demo.py --preview

render-e2e:
	python3 scripts/render_e2e.py

render-gpu-smoke:
	python3 scripts/render_e2e.py --gpu

.PHONY: render-faults render-demo visual-clean-check visual-release-check
render-faults:
	.client-venv/bin/python scripts/render_faults.py

render-demo:
	python3 scripts/render_demo.py

visual-clean-check:
	python3 scripts/visual_clean_check.py

visual-release-check:
	python3 scripts/visual_release_check.py

.PHONY: visual-regression
visual-regression:
	python3 scripts/visual_regression.py

.PHONY: pushup-e2e
pushup-e2e:
	$(RUN) --entrypoint python runtime scripts/v07_e2e.py
