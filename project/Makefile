setup:
	python -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -r requirements.txt

train:
	python -m src.models.train

eval:
	python -m src.models.evaluate

register:
	python - <<'PY'
from src.models.registry import register
print('Use train.py to register automatically.')
PY

serve:
	uvicorn src.service_online.app:app --host $${API_HOST:-0.0.0.0} --port $${API_PORT:-8000}

batch:
	python -m src.service_batch.entry --in data/sample.parquet --out out/preds.parquet --model best

smoke:
	pytest tests/smoke -q

contract:
	pytest tests/contract -q

test:
	pytest -q
