<# Stops the EGX Flow processes that scripts\start.ps1 started (and only those). #>
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root ".run\pids.json"
if (-not (Test-Path $pidFile)) { Write-Host "[EGX Flow] Nothing to stop."; exit 0 }
$saved = Get-Content $pidFile -Raw | ConvertFrom-Json
foreach ($prop in $saved.PSObject.Properties) {
    $proc = Get-Process -Id $prop.Value -ErrorAction SilentlyContinue
    # Guard against PID reuse: only ever stop a python or node process.
    if ($proc -and ($proc.ProcessName -match '^(python|pythonw|node)$')) {
        & taskkill /PID $prop.Value /T /F | Out-Null
        Write-Host "[EGX Flow] Stopped $($prop.Name) (PID $($prop.Value))."
    }
}
Remove-Item $pidFile -Force
exit 0
