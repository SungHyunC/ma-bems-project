<#
대시보드를 공개 사이트에 다시 배포합니다.
MA-BEMS\index.html과 data\를 site\public으로 복사하고, 배포 전 검사(페이지 스크립트 문법, config 형식, 비밀값 스캔)를
통과하면 GitHub에 푸시합니다. GitHub Actions가 같은 검사를 한 번 더 거친 뒤 GitHub Pages에 배포합니다.

  deploy\publish-site.cmd ["커밋 메시지"]
#>
param([string]$Message = 'site: update dashboard')

$ErrorActionPreference = 'Continue'
$Deploy = $PSScriptRoot
$Root = Split-Path -Parent $Deploy
$Site = Join-Path $Deploy 'site'

# catch up with commits pushed from another machine first, so the push below is a fast-forward
git -C $Site pull -q --rebase --autostash origin main

Copy-Item (Join-Path $Root 'index.html') (Join-Path $Site 'public\index.html') -Force
New-Item -ItemType Directory -Force (Join-Path $Site 'public\data') | Out-Null
Copy-Item (Join-Path $Root 'data\*') (Join-Path $Site 'public\data') -Recurse -Force

Push-Location $Site
try {
  node .github/scripts/check.mjs
  if ($LASTEXITCODE -ne 0) { Write-Host '! 검사를 통과하지 못해 배포하지 않습니다.' -ForegroundColor Red; exit 1 }
  git add -A public
  git diff --cached --quiet
  if ($LASTEXITCODE -eq 0) { Write-Host '바뀐 내용이 없습니다.'; exit 0 }
  git commit -q -m $Message
  git push -q origin main
  if ($LASTEXITCODE -ne 0) { Write-Host '! GitHub 푸시 실패: 인터넷 연결과 gh 로그인(gh auth status)을 확인하세요' -ForegroundColor Red; exit 1 }
  Write-Host '푸시했습니다. 1~2분 뒤 공개 사이트에 반영됩니다: https://github.com/SungHyunC/ma-bems/actions' -ForegroundColor Green
} finally {
  Pop-Location
}
