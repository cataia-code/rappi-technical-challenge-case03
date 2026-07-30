# Regenerates docs/index.html from apps/web/templates/dashboard.html + the latest
# pipeline output. Run after any run_pipeline.ps1 execution or template edit.
.\.venv\Scripts\python.exe apps\web\build_page.py
