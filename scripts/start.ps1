<#
  EGX Flow launcher (Windows). Sets everything up on first run, then starts the
  API and the UI on this computer only (127.0.0.1) and opens the browser.

    scripts\start.ps1                 # start (demo data unless .env says otherwise)
    scripts\start.ps1 -UiPort 3200    # use other ports
    scripts\start.ps1 -Rebuild        # force a fresh UI build
    scripts\stop.ps1                  # stop
#>
param(
    [int]$ApiPort = 8000,
    [int]$UiPort = 3100,
    [switch]$NoBrowser,
    [switch]$Rebuild
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$run = Join-Path $root ".run"
$venvPy = Join-Path $backend ".venv\Scripts\python.exe"
$apiUrl = "http://127.0.0.1:$ApiPort"
$uiUrl = "http://localhost:$UiPort"
# Probe over IPv4: "localhost" tries IPv6 first, which is slow to fail when the UI listens on 127.0.0.1 only.
$uiProbe = "http://127.0.0.1:$UiPort"
New-Item -ItemType Directory -Force $run | Out-Null

function Say([string]$m, [string]$c = "Cyan") { Write-Host "[EGX Flow] $m" -ForegroundColor $c }
function Fail([string]$m) { Write-Host "[EGX Flow] $m" -ForegroundColor Red; exit 1 }
function Test-Url([string]$u) {
    try { return ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $u).StatusCode -eq 200) } catch { return $false }
}
function Test-Health {
    try { return [bool](Invoke-RestMethod -TimeoutSec 2 "$apiUrl/api/health").ok } catch { return $false }
}
function Port-Busy([int]$p) {
    try { return [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction Stop) } catch { return $false }
}

# ---------------------------------------------------------------- already running?
if ((Test-Health) -and (Test-Url $uiProbe)) {
    Say "Already running at $uiUrl" "Green"
    if (-not $NoBrowser) { Start-Process $uiUrl }
    exit 0
}

# ---------------------------------------------------------------- prerequisites
$pyCmd = $null
foreach ($cand in @("py -3", "python", "python3")) {
    $parts = $cand.Split(" ")
    $exe = $parts[0]
    $pre = @(); if ($parts.Length -gt 1) { $pre = $parts[1..($parts.Length - 1)] }
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $v = $null
    try { $v = (& $exe @pre -c "import sys; print('%d.%d' % sys.version_info[:2])") 2>$null } catch { }
    if ($v -and ($v -match '^(\d+)\.(\d+)$') -and ([int]$Matches[1] -eq 3) -and ([int]$Matches[2] -ge 11)) {
        $pyCmd = @{ Exe = $exe; Pre = $pre; Version = "$v" }
        break
    }
}
if (-not (Test-Path $venvPy) -and -not $pyCmd) {
    Fail "Python 3.11 or newer was not found. Install it with:  winget install Python.Python.3.12"
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    $env:PATH = "$env:ProgramFiles\nodejs;$env:APPDATA\npm;$env:PATH"
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Fail "Node.js 20 or newer was not found. Install it with:  winget install OpenJS.NodeJS.LTS"
}
$nodeMajor = [int]((& node --version) -replace '^v(\d+)\..*$', '$1')
if ($nodeMajor -lt 20) { Fail "Node.js 20 or newer is required (found v$nodeMajor)." }

# ---------------------------------------------------------------- configuration
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root ".env.example") $envFile
    Say "Created .env from .env.example (demo mode, simulated data)."
}
$mode = "demo"
$m = Select-String -Path $envFile -Pattern '^\s*DATA_MODE\s*=\s*(\w+)' | Select-Object -First 1
if ($m) { $mode = $m.Matches[0].Groups[1].Value.ToLower() }

# ---------------------------------------------------------------- backend setup
if (-not (Test-Path $venvPy)) {
    Say "First run: creating the Python environment (Python $($pyCmd.Version))..."
    $pre = $pyCmd.Pre
    & $pyCmd.Exe @pre -m venv (Join-Path $backend ".venv")
    if (-not (Test-Path $venvPy)) { Fail "Could not create the Python environment." }
}
& $venvPy -c "import fastapi, uvicorn, sqlalchemy, alembic, pydantic_settings" 2>$null
if ($LASTEXITCODE -ne 0) {
    Say "Installing backend packages (about a minute)..."
    & $venvPy -m pip install --disable-pip-version-check -q -r (Join-Path $backend "requirements.txt")
    if ($LASTEXITCODE -ne 0) { Fail "Installing backend packages failed. See the messages above." }
}
if ($mode -eq "live") {
    & $venvPy -c "import younit" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Say "DATA_MODE=live needs the EFG Hermes Younit SDK, which is not installed. See README > Connect to EFG Hermes." "Yellow"
    }
}

# ---------------------------------------------------------------- frontend setup
Push-Location $frontend
if (-not (Test-Path "node_modules\next")) {
    Say "First run: installing UI packages (a minute or two)..."
    if (Test-Path "package-lock.json") { & npm ci --no-audit --no-fund } else { & npm install --no-audit --no-fund }
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "Installing UI packages failed. See the messages above." }
}
$env:NEXT_DIST_DIR = ".next-prod"
$env:NEXT_PUBLIC_API_BASE = "http://localhost:$ApiPort"
$env:NEXT_TELEMETRY_DISABLED = "1"
$buildId = Join-Path $frontend ".next-prod\BUILD_ID"
$stamp = Join-Path $run "ui-build.txt"
$need = $Rebuild -or -not (Test-Path $buildId) -or -not (Test-Path $stamp) -or ((Get-Content $stamp -Raw).Trim() -ne $env:NEXT_PUBLIC_API_BASE)
if (-not $need) {
    $built = (Get-Item $buildId).LastWriteTimeUtc
    $watch = @("src", "package.json", "next.config.ts") | ForEach-Object { Join-Path $frontend $_ }
    $newer = Get-ChildItem $watch -Recurse -File | Where-Object { $_.LastWriteTimeUtc -gt $built } | Select-Object -First 1
    if ($newer) { $need = $true }
}
if ($need) {
    if (Port-Busy $UiPort) { Pop-Location; Fail "Port $UiPort is in use, so the UI cannot be rebuilt/started. Run scripts\stop.ps1 or pass -UiPort." }
    Say "Building the UI (about a minute, only when it changed)..."
    & node node_modules\next\dist\bin\next build | Out-Null
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "The UI build failed. Run 'npm run build' in the frontend folder to see why." }
    Set-Content -Path $stamp -Value $env:NEXT_PUBLIC_API_BASE -Encoding ascii
}
Pop-Location

# ---------------------------------------------------------------- start
$pids = @{}
if (-not (Test-Health)) {
    if (Port-Busy $ApiPort) { Fail "Port $ApiPort is used by another program. Close it or pass -ApiPort." }
    $env:CORS_ORIGINS = "http://localhost:$UiPort,http://127.0.0.1:$UiPort"
    Say "Starting the engine ($mode mode) on $apiUrl ..."
    $p = Start-Process -FilePath $venvPy -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort" `
        -RedirectStandardOutput (Join-Path $run "api.log") -RedirectStandardError (Join-Path $run "api.err.log")
    $pids.api = $p.Id
}
if (-not (Test-Url $uiProbe)) {
    if (Port-Busy $UiPort) { Fail "Port $UiPort is used by another program. Close it or pass -UiPort." }
    Say "Starting the UI on $uiUrl ..."
    $p = Start-Process -FilePath "node" -WorkingDirectory $frontend -WindowStyle Hidden -PassThru `
        -ArgumentList "node_modules\next\dist\bin\next", "start", "-p", "$UiPort", "-H", "127.0.0.1" `
        -RedirectStandardOutput (Join-Path $run "ui.log") -RedirectStandardError (Join-Path $run "ui.err.log")
    $pids.ui = $p.Id
}
$pidFile = Join-Path $run "pids.json"
$old = @{}
if (Test-Path $pidFile) { try { (Get-Content $pidFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $old[$_.Name] = $_.Value } } catch { } }
foreach ($k in $pids.Keys) { $old[$k] = $pids[$k] }
$old | ConvertTo-Json | Set-Content -Path $pidFile -Encoding ascii

# ---------------------------------------------------------------- wait until ready
Say "Preparing market data (demo mode pre-generates 20 minutes of history; up to a minute)..."
$ok = $false
for ($i = 0; $i -lt 180; $i++) {
    if ((Test-Health) -and (Test-Url $uiProbe)) { $ok = $true; break }
    if ($pids.api -and -not (Get-Process -Id $pids.api -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Seconds 1
}
if (-not $ok) {
    Say "EGX Flow did not come up. Last engine messages:" "Red"
    Get-Content (Join-Path $run "api.err.log") -Tail 15 -ErrorAction SilentlyContinue
    exit 1
}
Say "Running at $uiUrl   (data mode: $mode)" "Green"
Say "Only this computer can reach it. Stop it with 'Stop EGX Flow.cmd' (or scripts\stop.ps1)."
if (-not $NoBrowser) { Start-Process $uiUrl }
exit 0
