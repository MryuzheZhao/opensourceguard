[CmdletBinding()]
param(
    [string]$Repo = "",
    [int]$Port = 8787,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

function Find-Python {
    $configured = [Environment]::GetEnvironmentVariable("OSG_PYTHON")
    $candidates = @(
        $configured,
        (Join-Path $Root ".venv\Scripts\python.exe"),
        (Join-Path $Root "venv\Scripts\python.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return @{ Path = $candidate; Prefix = @() }
        }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @{ Path = $python.Source; Prefix = @() } }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { return @{ Path = $launcher.Source; Prefix = @("-3") } }
    throw "没有找到 Python 3。请先安装 Python 3.10 或更高版本，再重新双击 start.bat。"
}

function Import-LocalConfig {
    $configPath = Join-Path $Root ".env.local"
    if (-not (Test-Path -LiteralPath $configPath)) { return }
    foreach ($line in Get-Content -LiteralPath $configPath -Encoding UTF8) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            $name = $Matches[1]
            if ($name -notmatch '^(OSG_|TYPESAFE_)') { continue }
            $value = $Matches[2].Trim()
            if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Test-ExistingService {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
        return $null -ne $health.status
    } catch { return $false }
}

Import-LocalConfig

if (-not $Repo) {
    $defaultRepo = Join-Path $Root "examples\buggy_csv"
    $answer = Read-Host "项目目录（直接回车使用演示项目）"
    $Repo = if ($answer.Trim()) { $answer.Trim().Trim('"') } else { $defaultRepo }
}
$Repo = [IO.Path]::GetFullPath($Repo)
if (-not (Test-Path -LiteralPath $Repo -PathType Container)) {
    throw "项目目录不存在：$Repo"
}

$url = "http://127.0.0.1:$Port/"
if (Test-ExistingService) {
    Write-Host "检测到已有 OpenSourceGuard 服务，直接打开：$url" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
}

$python = Find-Python
$arguments = @($python.Prefix + @("-m", "opensourceguard.cli", "serve", "--repo", $Repo, "--port", "$Port"))
$server = Start-Process -FilePath $python.Path -ArgumentList $arguments -WorkingDirectory $Root -WindowStyle Hidden -PassThru
try {
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        if ($server.HasExited) { throw "OpenSourceGuard 服务启动失败，请检查 Python 安装或端口 $Port 是否被占用。" }
        if (Test-ExistingService) { $ready = $true; break }
    }
    if (-not $ready) { throw "服务启动超时，请换一个端口重试，例如：start.bat <项目目录> 8788" }
    Write-Host "OpenSourceGuard 已启动：$url" -ForegroundColor Green
    Write-Host "关闭此窗口即可停止服务。配置文件：.env.local" -ForegroundColor DarkGray
    if (-not $NoBrowser) { Start-Process $url }
    while (-not $server.HasExited) { Start-Sleep -Seconds 1 }
} finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
}
