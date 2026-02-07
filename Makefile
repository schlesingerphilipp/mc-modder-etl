
SERVICE_NAME = llm-explore
SERVICE_VERSION = 0.0.1

######################################
#
# Local Poetry-Python commands
#
######################################

.PHONY: poetry-install
poetry-install: 
	poetry config virtualenvs.in-project true
	poetry install

.PHONY: poetry-install-no-dev
poetry-install-no-dev: 
	poetry config virtualenvs.in-project true
	poetry install --without=dev


.PHONY: install
install: poetry-install

.PHONY: install-no-dev
install-no-dev: poetry-install-no-dev


.PHONY: lock
lock:
	poetry lock
	
.PHONY: lint
lint: ## lint the project
	poetry run pylint $(SERVICE_NAME) tests


.PHONY: format
format: ## Format by pep8 standard
	poetry run black $(SERVICE_NAME) tests

.PHONY: format-check
format-check: ## Check formatting
	poetry run black $(SERVICE_NAME) tests --check

.PHONY: test
test:
	poetry run python -m pytest -vv .

.PHONY: activate
activate: # Activate virtual env
	poetry shell


