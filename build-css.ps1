# Compile the LGMED-iMMS stylesheet.
#   .\build-css.ps1          one-off production build (minified)
#   .\build-css.ps1 -Watch   rebuild on every template change during development
param([switch]$Watch)

$tailwind = Join-Path $PSScriptRoot "tools\tailwindcss.exe"
if (-not (Test-Path $tailwind)) {
    Write-Error "tools\tailwindcss.exe not found. See README.md - Stylesheet build."
    exit 1
}

$argsList = @("-i", "static/css/app.src.css", "-o", "static/css/app.css")
if ($Watch) { $argsList += "--watch" } else { $argsList += "--minify" }

& $tailwind @argsList
