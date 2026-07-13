$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $PSScriptRoot "fukua_rpa_core.cpp"
$out = Join-Path $root "fukua_rpa_core.dll"
$buildDir = Join-Path $PSScriptRoot "build"
$vcvarsCandidates = @(
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    "E:\GongJv\Visual_Studio\VC\Auxiliary\Build\vcvars64.bat"
)

$vcvars = $vcvarsCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $vcvars) {
    throw "Cannot find vcvars64.bat. Install Visual Studio Build Tools with C++ workload."
}

New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$obj = Join-Path $buildDir "fukua_rpa_core.obj"
$implib = Join-Path $buildDir "fukua_rpa_core.lib"
$dependencyReport = Join-Path $buildDir "fukua_rpa_core.dependencies.txt"
$headerReport = Join-Path $buildDir "fukua_rpa_core.headers.txt"

$cmd = "call `"$vcvars`" >nul && cl /nologo /O2 /MT /EHsc /std:c++17 /W4 " +
       "/D_WIN32_WINNT=0x0A00 /DWINVER=0x0A00 /LD `"$src`" /Fo`"$obj`" " +
       "/link /DLL /OUT:`"$out`" /IMPLIB:`"$implib`" " +
       "/SUBSYSTEM:WINDOWS,10.00 user32.lib gdi32.lib gdiplus.lib d3d11.lib dxgi.lib && " +
       "dumpbin /nologo /dependents `"$out`" > `"$dependencyReport`" && " +
       "dumpbin /nologo /headers `"$out`" > `"$headerReport`""

& $env:ComSpec /d /s /c $cmd
if ($LASTEXITCODE -ne 0) {
    throw "Native core build failed with exit code $LASTEXITCODE"
}

$dependencies = Get-Content -Raw -LiteralPath $dependencyReport
$headers = Get-Content -Raw -LiteralPath $headerReport
if ($dependencies -match "(?i)(VCRUNTIME|MSVCP|UCRTBASE|api-ms-win-crt)") {
    throw "Native core unexpectedly depends on a dynamic MSVC/UCRT runtime. /MT contract failed."
}
if ($headers -notmatch "(?i)8664 machine \(x64\)") {
    throw "Native core is not an x64 PE image."
}
if ($headers -notmatch "(?im)^\s*10\.00\s+subsystem version\s*$") {
    throw "Native core does not declare the Windows 10 subsystem baseline."
}

Write-Host "Built and PE-verified $out"
