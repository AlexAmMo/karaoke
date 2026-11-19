# Install a published portable release per user, preserving data and previous release on failure.
$ErrorActionPreference = 'Stop'
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
  throw 'Esta versión requiere Windows x64; Windows ARM no está validado.'
}
$Repo = 'AlexAmMo/karaoke'
$Version = $env:KARAOKE_VERSION
if (-not $Version) {
  try { $Release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest"; $Version = $Release.tag_name }
  catch { throw 'Todavía no hay una versión estable publicada. Consulta Releases en GitHub.' }
}
if ($Version -notmatch '^v?\d+\.\d+\.\d+([.-][a-zA-Z0-9.-]+)?$') { throw 'Versión no válida.' }
$Number = $Version -replace '^v', ''
$Asset = "Karaoke-$Number-windows-x86_64.zip"
$Base = "https://github.com/$Repo/releases/download/$Version"
$Work = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
$Target = Join-Path $env:LOCALAPPDATA 'Programs\Karaoke'
$Backup = "$Target.previous"
New-Item -ItemType Directory -Path $Work | Out-Null
try {
  $Archive = Join-Path $Work $Asset
  Write-Output "Descargando $Asset..."
  $Timer = [Diagnostics.Stopwatch]::StartNew()
  & {
    # Windows PowerShell 5.1 spends significant time redrawing per-block progress.
    # Limit the preference to these requests, even when invoked via irm | iex.
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -UseBasicParsing "$Base/$Asset" -OutFile $Archive
    Invoke-WebRequest -UseBasicParsing "$Base/$Asset.sha256" -OutFile "$Archive.sha256"
  }
  Write-Output ("Descarga completada en {0:N1} s. Verificando SHA-256..." -f $Timer.Elapsed.TotalSeconds)
  $Expected = ((Get-Content "$Archive.sha256" -TotalCount 1) -split '\s+')[0]
  if ($Expected -notmatch '^[0-9a-fA-F]{64}$') { throw 'Archivo de verificación no válido.' }
  if ((Get-FileHash $Archive -Algorithm SHA256).Hash -ne $Expected) { throw 'La descarga no supera la verificación SHA-256.' }
  Write-Output 'Extrayendo Karaoke...'
  Expand-Archive $Archive -DestinationPath (Join-Path $Work 'extracted')
  $App = Join-Path $Work 'extracted\Karaoke'
  if (-not (Test-Path (Join-Path $App 'karaoke.exe'))) { throw 'El paquete está incompleto.' }
  if (Test-Path $Backup) { throw "Revisa la copia de actualización anterior: $Backup" }
  if (Get-Process karaoke -ErrorAction SilentlyContinue) { throw 'Cierra Karaoke antes de actualizar.' }
  New-Item -ItemType Directory -Force -Path (Split-Path $Target) | Out-Null
  if (Test-Path $Target) { Move-Item $Target $Backup }
  try { Move-Item $App $Target }
  catch { if (Test-Path $Backup) { Move-Item $Backup $Target }; throw }
  if (Test-Path $Backup) { Remove-Item -Recurse -Force $Backup }
  $Shell = New-Object -ComObject WScript.Shell
  $Shortcut = $Shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'Karaoke.lnk'))
  $Shortcut.TargetPath = Join-Path $Target 'karaoke.exe'
  $Shortcut.WorkingDirectory = $Target
  $Shortcut.Save()
  Write-Output "Karaoke instalado en $Target. Ábrelo desde el menú Inicio."
  Write-Output 'La biblioteca y los ajustes se conservan en LocalAppData\Karaoke.'
} finally { Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue }
