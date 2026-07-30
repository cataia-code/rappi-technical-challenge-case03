# Runs the batch pipeline over the 150 cases and rebuilds the web dashboard.
# Usage: .\scripts\run_pipeline.ps1 [-NoLlm] [-Limit 15]
param(
    [switch]$NoLlm,
    [int]$Limit
)

$env:PYTHONPATH = "src"
$py = ".\.venv\Scripts\python.exe"

$pipelineArgs = @()
if ($NoLlm) { $pipelineArgs += "--no-llm" }
if ($Limit) { $pipelineArgs += "--limit"; $pipelineArgs += $Limit }

& $py -m pipeline @pipelineArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py apps\web\build_page.py
