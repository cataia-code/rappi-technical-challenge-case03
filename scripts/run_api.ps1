# Starts the FastAPI HTTP boundary with autoreload.
$env:PYTHONPATH = "src"
.\.venv\Scripts\uvicorn.exe apps.api.main:app --reload
