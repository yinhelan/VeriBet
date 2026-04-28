VENV=.venv
PY=$(VENV)/bin/python
PIP=$(VENV)/bin/pip

PACK=packs/veribet_regression_pack_v1.yaml
BUNDLE=prompts/veribet_prompt_bundle_v412_candidate.yaml

.PHONY: setup targeted full resilient live batch

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

targeted:
	scripts/run_targeted.sh

full:
	scripts/run_veribet.sh

resilient:
	scripts/run_veribet_resilient.sh

live:
	scripts/run_live.sh inputs/live_match_input.json live_result.json

batch:
	scripts/run_live_batch.sh inputs live_outputs_batch
