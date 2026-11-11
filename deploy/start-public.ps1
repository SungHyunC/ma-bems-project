<#
MA-BEMS 공개 모드: 게이트웨이 + Cloudflare 터널 + 공개 사이트 설정

  deploy\start-public.cmd     켜기 (이미 켜져 있으면 터널을 새로 엽니다)
  deploy\stop-public.cmd      끄기 (공개 사이트에는 "운영자 PC: 꺼짐"으로 표시)

하는 일
  1. 게이트웨이(server\mabems_server.py)가 꺼져 있으면 켭니다. 공개 API는 127.0.0.1:5179에서만 듣고
     모든 호출에 접근 키가 필요합니다 (키 목록: deploy\keys.cmd).
  2. 그 포트로 Cloudflare Quick Tunnel을 엽니다. 계정이 필요 없고, 열 때마다 https://*.trycloudflare.com
     주소가 새로 생깁니다.
  3. 새 주소를 site\public\config.json에 쓰고 GitHub에 푸시합니다. GitHub Pages가 1분쯤 뒤 다시 배포하면
     공개 사이트의 AI 탭이 이 주소로 연결됩니다.
#>
param([switch]$Stop, [switch]$NoPush, [switch]$RestartGateway)   # -RestartGateway: reload server code, keep the tunnel

$ErrorActionPreference = 'Continue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Deploy = $PSScriptRoot
$Root = Split-Path -Parent $Deploy
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$Server = Join-Path $Root 'server\mabems_server.py'
$Cf = Join-Path $Deploy 'bin\cloudflared.exe'
$Site = Join-Path $Deploy 'site'
$Logs = Join-Path $Deploy 'logs'
$State = Join-Path $Logs 'state.json'
New-Item -ItemType Directory -Force $Logs | Out-Null

function Get-EnvValue([string]$Name, [string]$Default) {
  $envFile = Join-Path $Root '.env'
  if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile -Encoding UTF8) {
      if ($line -match "^\s*$Name\s*=\s*(.*)$") { $v = $Matches[1].Trim().Trim('"').Trim("'"); if ($v) { return $v } }
    }
  }
  return $Default
}
$Port = [int](Get-EnvValue 'MABEMS_PORT' '5178')
$PublicPort = [int](Get-EnvValue 'MABEMS_PUBLIC_PORT' '5179')
$SiteUrl = Get-EnvValue 'MABEMS_SITE_URL' 'https://sunghyunc.github.io/ma-bems/'

# a real connection attempt: after many short connections Windows listed the gateway's listening socket as FinWait1
# (Get-NetTCPConnection -State Listen found nothing while the port answered), so the restart reported a failure
function Test-Listening([int]$P) {
  $c = New-Object Net.Sockets.TcpClient
  try { $r = $c.BeginConnect('127.0.0.1', $P, $null, $null); return [bool]($r.AsyncWaitHandle.WaitOne(400) -and $c.Connected) }
  catch { return $false } finally { $c.Close() }
}
function Read-State { if (Test-Path $State) { try { return (Get-Content $State -Raw | ConvertFrom-Json) } catch { } }; return $null }
function Stop-Pid($Id) { if ($Id) { Stop-Process -Id $Id -Force -ErrorAction SilentlyContinue } }
function Stop-OurTunnels { Get-Process cloudflared -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Cf } | Stop-Process -Force -ErrorAction SilentlyContinue }

function Start-Gateway {
  # a gateway started before the public API existed may hold the usual port: run beside it
  $pagePort = if (Test-Listening $Port) { $Port + 2 } else { $Port }
  $gw = Start-Process -PassThru -WindowStyle Hidden -FilePath $Py -WorkingDirectory $Root `
    -ArgumentList @("`"$Server`"", '--port', "$pagePort", '--public-port', "$PublicPort") `
    -RedirectStandardOutput (Join-Path $Logs 'gateway.out.log') -RedirectStandardError (Join-Path $Logs 'gateway.log')
  # up to 40 s: before it listens the gateway asks Ollama for its models and imports the Claude SDK, which took over 15 s twice
  for ($i = 0; $i -lt 160 -and -not (Test-Listening $PublicPort); $i++) { Start-Sleep -Milliseconds 250 }
  if (-not (Test-Listening $PublicPort)) { Write-Host "! 게이트웨이가 시작되지 않았습니다: $Logs\gateway.log" -ForegroundColor Red; exit 1 }
  Write-Host "  게이트웨이: 시작 (대시보드 http://127.0.0.1:$pagePort , 공개 API 127.0.0.1:$PublicPort)"
  # .venv\Scripts\python.exe is a launcher that runs the real interpreter as a child: keep both ids, the child holds the
  # ports. Found by parent id (the listening socket of a just-killed gateway can still show up with process id 0).
  $kids = @()
  for ($i = 0; $i -lt 12 -and -not $kids; $i++) {
    $kids = @((Get-CimInstance Win32_Process -Filter "ParentProcessId=$($gw.Id)" -ErrorAction SilentlyContinue).ProcessId)
    if (-not $kids) { Start-Sleep -Milliseconds 250 }
  }
  return @(@($gw.Id) + $kids | Where-Object { $_ -gt 0 } | Select-Object -Unique)
}

function Stop-Gateways {
  # every running copy of the gateway (a restart that raced an old one left two listening on the same ports)
  foreach ($p in @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*mabems_server.py*' })) { Stop-Pid $p.ProcessId }
}

function Publish-Gateway([string]$Url) {
  $cfg = [ordered]@{
    gateway = $Url
    updated = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    note    = 'Written by deploy/start-public.ps1 on the operator PC: the Cloudflare tunnel address of the AI gateway, or empty while the PC is offline.'
  }
  [IO.File]::WriteAllText((Join-Path $Site 'public\config.json'), (($cfg | ConvertTo-Json) + "`n"), (New-Object Text.UTF8Encoding $false))
  if ($NoPush) { Write-Host '  config.json만 바꿨습니다 (-NoPush: 푸시 안 함)'; return $true }
  git -C $Site add public/config.json
  git -C $Site commit -q -m ('config: gateway ' + $(if ($Url) { 'online' } else { 'offline' }))
  git -C $Site push -q origin main
  if ($LASTEXITCODE -ne 0) { Write-Host '  ! GitHub 푸시 실패: 인터넷 연결과 gh 로그인(gh auth status)을 확인하세요' -ForegroundColor Yellow; return $false }
  return $true
}

# ---------- stop ----------
if ($Stop) {
  $s = Read-State
  if ($s) { Stop-Pid $s.tunnel; if ($s.gatewayStarted) { foreach ($id in @($s.gateway)) { Stop-Pid $id }; Stop-Gateways } }
  Stop-OurTunnels
  Remove-Item $State -ErrorAction SilentlyContinue
  $null = Publish-Gateway ''
  Write-Host '공개 모드를 껐습니다. 1분쯤 뒤 공개 사이트의 AI 탭에 "운영자 PC: 꺼짐"이 표시됩니다.' -ForegroundColor Cyan
  return
}

# ---------- restart the gateway only (after a server code change): the tunnel and its address stay ----------
if ($RestartGateway) {
  $s = Read-State
  if ($s) { foreach ($id in @($s.gateway)) { Stop-Pid $id } }
  foreach ($id in @((Get-NetTCPConnection -State Listen -LocalPort $PublicPort -ErrorAction SilentlyContinue).OwningProcess)) { Stop-Pid $id }
  Stop-Gateways
  # wait for both ports: if the page port still looks taken, Start-Gateway moves the dashboard to 5180
  for ($i = 0; $i -lt 40 -and ((Test-Listening $PublicPort) -or (Test-Listening $Port)); $i++) { Start-Sleep -Milliseconds 250 }
  $ids = Start-Gateway
  if ($s) {
    $s.gateway = $ids; $s.gatewayStarted = $true
    $s | ConvertTo-Json | Set-Content -Path $State -Encoding UTF8
    Write-Host "  터널은 그대로입니다: $($s.url)"
  }
  return
}

# ---------- start ----------
Write-Host 'MA-BEMS 공개 모드를 켭니다...' -ForegroundColor Cyan
foreach ($f in @($Py, $Server, $Cf, (Join-Path $Site '.git'))) {
  if (-not (Test-Path $f)) { Write-Host "! 없음: $f" -ForegroundColor Red; exit 1 }
}
try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 }
catch { Write-Host '  ! Ollama가 꺼져 있습니다. Ollama 앱을 켜야 로컬 모델이 답합니다.' -ForegroundColor Yellow }

$old = Read-State
if ($old) { Stop-Pid $old.tunnel }        # a new tunnel gets a new address: close the old one first
Stop-OurTunnels

# 1. gateway with the public API
$gwPid = $null; $gwStarted = $false
if (Test-Listening $PublicPort) {
  Write-Host "  게이트웨이: 이미 실행 중 (공개 API 127.0.0.1:$PublicPort)"
  if ($old -and $old.gatewayStarted) { $gwPid = $old.gateway; $gwStarted = $true }
} else {
  $gwPid = Start-Gateway
  $gwStarted = $true
}

# 2. Cloudflare quick tunnel (a request can fail now and then: retry)
$url = $null; $tn = $null
$tlog = Join-Path $Logs 'tunnel.log'
for ($try = 1; $try -le 3 -and -not $url; $try++) {
  Remove-Item $tlog -ErrorAction SilentlyContinue
  $tn = Start-Process -PassThru -WindowStyle Hidden -FilePath $Cf `
    -ArgumentList @('tunnel', '--no-autoupdate', '--url', "http://127.0.0.1:$PublicPort") `
    -RedirectStandardError $tlog -RedirectStandardOutput (Join-Path $Logs 'tunnel.out.log')
  for ($i = 0; $i -lt 60 -and -not $url -and -not $tn.HasExited; $i++) {
    Start-Sleep -Milliseconds 500
    $m = Select-String -Path $tlog -Pattern 'https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($m) { $url = $m.Matches[0].Value }
  }
  if (-not $url) { Stop-Pid $tn.Id; Write-Host "  터널 요청 실패 ($try/3), 다시 시도합니다..."; Start-Sleep -Seconds 2 }
}
if (-not $url) { Write-Host "! Cloudflare 터널을 열지 못했습니다. 인터넷 연결과 $tlog 를 확인하세요." -ForegroundColor Red; exit 1 }

# 3. wait until the new address answers (its DNS name can take a few seconds)
$ok = $false
for ($i = 0; $i -lt 40 -and -not $ok; $i++) {
  try { $ok = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri "$url/healthz").StatusCode -eq 200 } catch { Start-Sleep -Seconds 1 }
}
Write-Host ("  터널: $url " + $(if ($ok) { '(응답 확인)' } else { '(아직 응답 없음: 잠시 뒤 연결될 수 있습니다)' }))

@{ gateway = $gwPid; gatewayStarted = $gwStarted; tunnel = $tn.Id; url = $url; started = (Get-Date).ToString('s') } |
  ConvertTo-Json | Set-Content -Path $State -Encoding UTF8

# 4. tell the public site where the gateway is
$pushed = Publish-Gateway $url

Write-Host ''
Write-Host '공개 모드가 켜졌습니다.' -ForegroundColor Green
Write-Host "  공개 사이트   $SiteUrl" $(if ($pushed -and -not $NoPush) { ' (새 주소 반영까지 1분쯤)' } else { '' })
Write-Host "  게이트웨이    $url  (접근 키 필요)"
Write-Host '  키와 공유 링크  deploy\keys.cmd'
Write-Host '  끄기          deploy\stop-public.cmd'
Write-Host '  PC가 절전에 들어가면 AI가 끊깁니다. 발표 중에는 절전을 꺼 두세요.'
