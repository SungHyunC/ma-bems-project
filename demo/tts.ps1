<#
Korean narration with the Windows built-in voice (Microsoft Heami, OneCore), no download or online service.

  powershell -ExecutionPolicy Bypass -File demo\tts.ps1 -Json lines.json -OutDir wav [-Rate 1.05]

lines.json: [{"id": "s1_1", "say": "읽을 문장"}, ...]  ->  wav\s1_1.wav (16-bit PCM)
#>
param([Parameter(Mandatory = $true)][string]$Json, [Parameter(Mandatory = $true)][string]$OutDir, [double]$Rate = 1.05)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Wait-Op($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait() | Out-Null; return $t.Result }

$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.Language -eq 'ko-KR' } | Select-Object -First 1
if (-not $voice) { throw 'No Korean voice installed (Settings > Time & language > Speech)' }
$synth.Voice = $voice
New-Item -ItemType Directory -Force $OutDir | Out-Null

$items = Get-Content $Json -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($it in $items) {
    $text = [Security.SecurityElement]::Escape([string]$it.say)
    $ssml = "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='ko-KR'><prosody rate='$Rate'>$text</prosody></speak>"
    $stream = Wait-Op ($synth.SynthesizeSsmlToStreamAsync($ssml)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
    $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
    $size = [uint32]$stream.Size
    $null = Wait-Op ($reader.LoadAsync($size)) ([uint32])
    $bytes = New-Object byte[] $size
    $reader.ReadBytes($bytes)
    [IO.File]::WriteAllBytes((Join-Path $OutDir ($it.id + '.wav')), $bytes)
    Write-Host ("{0}  {1} bytes" -f $it.id, $size)
}
Write-Host ("voice: " + $voice.DisplayName)
