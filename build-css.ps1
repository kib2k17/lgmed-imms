# Compile the LGMED-IMMS stylesheet.
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

# The dark theme is derived from the compiled stylesheet; rebuild it too.
# (A -Watch run never reaches here: build once more before committing.)
$python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
& $python (Join-Path $PSScriptRoot "manage.py") build_dark_css
