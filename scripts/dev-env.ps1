# Dot-source this in PowerShell before working:  . .\scripts\dev-env.ps1
# Points every cache, the interpreter and the virtualenv at one data directory, so that they do not land on the system drive.
$data = "data"
foreach ($d in @("", "\uv-cache", "\uv-python", "\hf", "\corpus", "\postgres", "\ollama")) {
    $p = "$data$d"
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Force $p | Out-Null }
}
$env:ORDERORDER_DATA_DIR    = $data
$env:UV_CACHE_DIR           = "$data\uv-cache"
$env:UV_PYTHON_INSTALL_DIR  = "$data\uv-python"
$env:UV_PROJECT_ENVIRONMENT = "$data\venv"
$env:HF_HOME                = "$data\hf"
$env:OLLAMA_MODELS          = "$data\ollama"
Write-Host "OrderOrder dev environment: data and caches under $data"
Write-Host "Next: uv sync        (installs into $data\venv)"
Write-Host "      uv run orderorder --help"
