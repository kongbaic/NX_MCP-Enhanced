param(
    [string]$Workspace = "C:\\Users\\Kavin\\NX_MCP_FAST_BASELINE"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$benchRoot = Join-Path $repoRoot "benchmarks\\text_extraction"
$imagesRoot = Join-Path $benchRoot "images"

New-Item -ItemType Directory -Force -Path $imagesRoot | Out-Null

$shkssSource = Join-Path $Workspace "reader-crops\\overview.png"
if (-not (Test-Path $shkssSource)) {
    throw "SHKSS source image not found: $shkssSource"
}
Copy-Item -Force $shkssSource (Join-Path $imagesRoot "drawing-01-shkss20-40.png")

Invoke-WebRequest -Uri "https://raw.githubusercontent.com/Aadityajain-hub/AutoCAD_2D_Drawings/main/2D%20PROFILE%20DRAWING%20WITH%20RADIAL%20AND%20ANGULAR%20DIMENSION.png" -OutFile (Join-Path $imagesRoot "drawing-02-radial-angular.png")

Invoke-WebRequest -Uri "https://raw.githubusercontent.com/SivaTX92/AutoCAD-Task-1/main/Screenshot%20AutoCAD%20Task%201.png" -OutFile (Join-Path $imagesRoot "drawing-03-baseplate.png")

$manifest = @{
    schema = "text-extraction-bakeoff-v1"
    cases = @(
        @{
            case_id = "drawing-01-shkss20-40"
            image = "images/drawing-01-shkss20-40.png"
            complete_token_inventory = $false
            expected_tokens = @("40","32","66","20","24","18","8","6.6","40±0.02","H7")
        }
        @{
            case_id = "drawing-02-radial-angular"
            image = "images/drawing-02-radial-angular.png"
            complete_token_inventory = $false
            expected_tokens = @("R40","R10","R90","R100","R20","R70","R30","R15","10°","50°","30","70","15","50")
        }
        @{
            case_id = "drawing-03-baseplate"
            image = "images/drawing-03-baseplate.png"
            complete_token_inventory = $false
            expected_tokens = @("180.00","120.00","Ø12","10")
        }
    )
}

$manifestPath = Join-Path $benchRoot "manifest.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $manifestPath

Write-Host "Prepared:"
Write-Host "  $manifestPath"
Write-Host "  $imagesRoot"
