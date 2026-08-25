[CmdletBinding()]
param(
    [string]$WikiPath = (Join-Path $PSScriptRoot ".."),
    [string]$LinkPath,
    [switch]$UseSymbolicLink,
    [string]$InstructionsPath = (Join-Path $env:USERPROFILE ".copilot\copilot-instructions.md"),
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$wikiRoot = (Resolve-Path -LiteralPath $WikiPath).Path
$requiredPaths = @("AGENTS.md", "index.md", "log.md", "wiki")
$missingPaths = $requiredPaths | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $wikiRoot $_))
}

if ($missingPaths) {
    throw "Wiki root is missing required paths: $($missingPaths -join ', ')"
}

$configuredPath = $wikiRoot
if ($LinkPath) {
    if (Test-Path -LiteralPath $LinkPath) {
        throw "Link path already exists: $LinkPath"
    }

    $linkParent = Split-Path -Parent $LinkPath
    if (-not (Test-Path -LiteralPath $linkParent)) {
        New-Item -ItemType Directory -Path $linkParent | Out-Null
    }

    $linkType = if ($UseSymbolicLink) { "SymbolicLink" } else { "Junction" }
    New-Item -ItemType $linkType -Path $LinkPath -Target $wikiRoot | Out-Null
    $configuredPath = (Get-Item -LiteralPath $LinkPath).FullName
}

if ((Test-Path -LiteralPath $InstructionsPath) -and -not $Force) {
    throw "Instructions file already exists: $InstructionsPath. Re-run with -Force to replace it."
}

$instructionsDirectory = Split-Path -Parent $InstructionsPath
if (-not (Test-Path -LiteralPath $instructionsDirectory)) {
    New-Item -ItemType Directory -Path $instructionsDirectory | Out-Null
}

$templatePath = Join-Path $wikiRoot "templates\copilot-instructions.md"
$instructions = Get-Content -LiteralPath $templatePath -Raw
$instructions = $instructions.Replace("C:\path\to\llm-wiki", $configuredPath)
Set-Content -LiteralPath $InstructionsPath -Value $instructions -Encoding utf8

Write-Output "Copilot instructions installed: $InstructionsPath"
Write-Output "Wiki path configured: $configuredPath"
