# One command to reproduce the registered model:  make reproduce   (or: make reproduce-docker)
.PHONY: setup reproduce reproduce-docker baseline mlflow-ui export-runs test

setup:            ## install the training dependencies into the current Python
	pip install -e ".[train,dev]"

reproduce:        ## validate -> leakage -> prepare -> baselines -> train -> register, then diff metrics
	bash scripts/reproduce.sh

reproduce-docker: ## the same inside Docker, logging to the compose MLflow at http://localhost:5000
	docker compose --profile train run --rm train

baseline:         ## data checks and baselines only (CPU, a few minutes)
	bash scripts/reproduce.sh baseline

mlflow-ui:        ## browse local runs and the registry at http://localhost:5001
	mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5001

export-runs:      ## write runs and registry to docs/mlflow/ for submission
	python scripts/export_mlflow.py --out docs/mlflow

test:
	pytest -q
