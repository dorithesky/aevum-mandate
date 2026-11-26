PY ?= python3
export PYTHONPATH := agent
export PATH := $(HOME)/.foundry/bin:$(PATH)

.PHONY: install test contracts-test test-e2e invoices demo deploy setup scenario export clean

install:
	$(PY) -m pip install -r requirements.txt

test: contracts-test
	$(PY) -m pytest agent/tests -q

contracts-test:
	cd contracts && forge test

test-e2e:
	$(PY) scripts/local_e2e.py

deploy:
	$(PY) -m mandate.cli deploy

setup:
	$(PY) -m mandate.cli setup

invoices:
	$(PY) -m mandate.cli invoices

scenario:
	$(PY) -m mandate.cli scenario

export:
	$(PY) -m mandate.cli export

demo:
	$(PY) server/app.py

clean:
	rm -rf contracts/out contracts/cache state/deployment.json state/cases.json
