[CmdletBinding()]
param([string]$ModelId = "")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$configPath = Join-Path $Root ".env.local"
if (Test-Path -LiteralPath $configPath) {
    foreach ($line in Get-Content -LiteralPath $configPath -Encoding UTF8) {
        if ($line -match '^\s*(OSG_MODELSCOPE_TOKEN)\s*=\s*(.*?)\s*$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim([char]34), "Process")
        }
    }
}
if (-not $ModelId) { $ModelId = Read-Host "ModelScope space ID (example: yourname/opensourceguard)" }
if (-not $ModelId) { throw "ModelScope space ID is required." }
if (-not $env:OSG_MODELSCOPE_TOKEN) { throw "OSG_MODELSCOPE_TOKEN is missing. Put it in .env.local or the current shell." }

$python = if ($env:OSG_PYTHON -and (Test-Path -LiteralPath $env:OSG_PYTHON)) { $env:OSG_PYTHON } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $python) { throw "Python was not found." }
$answer = Read-Host "Upload the space/ bundle to ModelScope space $ModelId? Type YES to continue"
if ($answer -cne "YES") { Write-Host "Upload cancelled."; exit 0 }

$code = @'
import json, sys
from pathlib import Path
from opensourceguard.modelscope import publish
result = publish(Path(sys.argv[1]), sys.argv[2], kind="space", visibility="public", description="OpenSourceGuard local control center", confirm=True)
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result.get("ok") else 1)
'@
& $python -c $code $Root $ModelId
