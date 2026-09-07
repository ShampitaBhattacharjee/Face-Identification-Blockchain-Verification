PYTHON ?= python
IMAGE  ?= samples/photo.jpg
CHAIN  ?= amoy

.PHONY: help install install-dev deploy run run-crop verify test lint dashboard docker clean

help:
	@echo "make install      - install runtime deps (builds dlib, takes a few minutes)"
	@echo "make install-dev  - lightweight deps for tests/lint"
	@echo "make deploy       - compile + deploy FaceMatchRegistry to \$$CHAIN"
	@echo "make run          - run the pipeline on \$$IMAGE"
	@echo "make verify ID=0  - read record back from chain and check \$$IMAGE"
	@echo "make test / lint  - unit tests / ruff"
	@echo "make dashboard    - launch the optional Streamlit UI"

install:
	$(PYTHON) -m pip install -r requirements.txt

install-dev:
	$(PYTHON) -m pip install -r requirements-dev.txt

deploy:
	$(PYTHON) scripts/deploy.py --chain $(CHAIN)

run:
	$(PYTHON) main.py --image $(IMAGE) --chain $(CHAIN)

run-crop:
	$(PYTHON) main.py --image $(IMAGE) --chain $(CHAIN) --use-crop

verify:
	$(PYTHON) scripts/verify.py --record-id $(ID) --image $(IMAGE) --chain $(CHAIN)

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

dashboard:
	$(PYTHON) -m streamlit run dashboard/app.py

docker:
	docker build -t face-id-blockchain-verification .

clean:
	rm -rf output .pytest_cache .ruff_cache
