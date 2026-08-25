param (
    [string]$Arg
)

# Configuration
$PyProjectFile = "pyproject.toml"

# Functions
function Get-CurrentVersion {
    $Content = Get-Content $PyProjectFile -Raw
    $Match = [regex]::Match($Content, 'version = "(.*)"')
    if ($Match.Success) {
        return $Match.Groups[1].Value
    }
    return $null
}

function Bump-Version {
    param (
        [string]$Current,
        [string]$Type  # patch, minor, major
    )
    
    $Parts = $Current -split '\.'
    [int]$Major = $Parts[0]
    [int]$Minor = $Parts[1]
    [int]$Patch = $Parts[2]
    
    switch ($Type) {
        "patch" {
            $Patch++
        }
        "minor" {
            $Minor++
            $Patch = 0
        }
        "major" {
            $Major++
            $Minor = 0
            $Patch = 0
        }
    }
    
    return "$Major.$Minor.$Patch"
}

# --- Main ---

if (-not $Arg) {
    Write-Host "Usage: .\release.ps1 [patch|minor|major|vX.Y.Z]" -ForegroundColor Red
    exit 1
}

$CurrentVersion = Get-CurrentVersion
$NewVersion = ""

if ($Arg -in @("patch", "minor", "major")) {
    Write-Host "Bumping version ($Arg) from $CurrentVersion..." -ForegroundColor Cyan
    $NewVersion = Bump-Version -Current $CurrentVersion -Type $Arg
} else {
    $NewVersion = $Arg
    # Strip leading 'v' if present for pyproject.toml consistency
    $NewVersion = $NewVersion -replace "^v", ""
}

$VersionTag = "v$NewVersion"

Write-Host "Target Version: $NewVersion" -ForegroundColor Green
Write-Host "Target Tag:     $VersionTag" -ForegroundColor Green

# 1. Update pyproject.toml if version changed

if (Test-Path $PyProjectFile) {
    $Content = Get-Content $PyProjectFile -Raw
    $CurrentVersionMatch = [regex]::Match($Content, 'version = "(.*)"')
    
    if ($CurrentVersionMatch.Success) {
        $CurrentVersion = $CurrentVersionMatch.Groups[1].Value
        
        if ($CleanVersion -ne $CurrentVersion) {
            Write-Host "Updating $PyProjectFile from $CurrentVersion to $CleanVersion..." -ForegroundColor Cyan
            $NewContent = $Content -replace 'version = ".*"', "version = ""$CleanVersion"""
            Set-Content $PyProjectFile $NewContent
            
            Write-Host "Committing version bump..." -ForegroundColor Cyan
            git add $PyProjectFile
            git commit -m "chore: bump version to $CleanVersion"
            git push
        }
    }
}

Write-Host "Preparing to release version $Version..." -ForegroundColor Cyan

# Check if tag exists
if (git tag -l $Version) {
    Write-Host "Tag $Version already exists." -ForegroundColor Yellow
    $response = Read-Host "Do you want to delete the existing tag and recreate it? (y/n)"
    if ($response -eq 'y') {
        git tag -d $Version
        git push origin :refs/tags/$Version
        Write-Host "Deleted existing tag." -ForegroundColor Green
    }
    else {
        Write-Host "Aborting release." -ForegroundColor Red
        exit 1
    }
}

# Create tag
Write-Host "Creating tag $Version..." -ForegroundColor Cyan
git tag $Version
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to create tag." -ForegroundColor Red
    exit 1
}

# Push tag
Write-Host "Pushing tag to origin..." -ForegroundColor Cyan
git push origin $Version
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to push tag." -ForegroundColor Red
    exit 1
}

# Create GitHub Release
Write-Host "Creating GitHub Release..." -ForegroundColor Cyan
gh release create $Version --generate-notes --title "Release $Version"

if ($LASTEXITCODE -eq 0) {
    Write-Host "Release $Version created successfully!" -ForegroundColor Green
    Write-Host "The GitHub Action 'Publish to PyPI' should now be running." -ForegroundColor Cyan
    Write-Host "Check status at: https://github.com/fritzprix/chess-mcp-server/actions" -ForegroundColor Gray
}
else {
    Write-Host "Failed to create GitHub release." -ForegroundColor Red
    exit 1
}
