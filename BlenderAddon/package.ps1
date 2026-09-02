$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'a2f_local'
$destination = Join-Path $PSScriptRoot 'a2f_local.zip'
$bin = Join-Path $source 'bin'
$pycache = Join-Path $source '__pycache__'
if (Test-Path -LiteralPath $pycache) {
    Remove-Item -LiteralPath $pycache -Recurse -Force
}
New-Item -ItemType Directory -Path $bin -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\Engine\build\Release\a2f_blender_exporter.exe') -Destination $bin -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\Engine\build\Release\audio2x.dll') -Destination $bin -Force
Compress-Archive -LiteralPath $source -DestinationPath $destination -Force
Write-Host "Created $destination"
