[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "kindle-koreader-handoff.tex"
$build = Join-Path $PSScriptRoot "build"
$output = Join-Path $PSScriptRoot "kindle-koreader-handoff.pdf"

$xelatexCandidates = @(
    "C:\Program Files\MiKTeX\miktex\bin\x64\xelatex.exe",
    (Get-Command xelatex.exe -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

if ($xelatexCandidates.Count -eq 0) {
    throw "XeLaTeX was not found. Install MiKTeX or add xelatex.exe to PATH."
}

$xelatex = $xelatexCandidates[0]
New-Item -ItemType Directory -Path $build -Force | Out-Null

Push-Location $PSScriptRoot
try {
    for ($pass = 1; $pass -le 3; $pass++) {
        Write-Host "XeLaTeX pass $pass of 3..."
        & $xelatex -interaction=nonstopmode -halt-on-error -output-directory="$build" "$source"
        if ($LASTEXITCODE -ne 0) {
            throw "XeLaTeX failed on pass $pass. See build\kindle-koreader-handoff.log."
        }
    }
} finally {
    Pop-Location
}

Copy-Item -LiteralPath (Join-Path $build "kindle-koreader-handoff.pdf") -Destination $output -Force
Write-Host "Built: $output"
