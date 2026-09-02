param(
    [string]$SdkRoot = (Join-Path $PSScriptRoot '..\Audio2Face-3D-SDK'),
    [string]$BuildType = 'Release'
)

$ErrorActionPreference = 'Stop'
$cmake = Join-Path $PSScriptRoot '..\CMake\bin\cmake.exe'
if (-not (Test-Path -LiteralPath $cmake)) {
    $cmake = 'cmake'
}

$buildDir = Join-Path $PSScriptRoot 'build'
& $cmake -S $PSScriptRoot -B $buildDir -A x64 -DA2F_SDK_ROOT="$SdkRoot"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $cmake --build $buildDir --config $BuildType --parallel
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$outputDir = Join-Path $buildDir $BuildType
Copy-Item -LiteralPath (Join-Path $SdkRoot 'build\audio2x-sdk\bin\audio2x.dll') -Destination $outputDir -Force
Write-Host "Exporter built at $outputDir\a2f_blender_exporter.exe"

