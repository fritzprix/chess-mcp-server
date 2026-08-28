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
        [string]$Type  # patch, minor, major, beta, rc
    )

    if ($Type -in @("beta", "rc")) {
        $Suffix = if ($Type -eq "beta") { "b" } else { "rc" }
        if ($Current -match '^(\d+\.\d+\.\d+)(b|rc)(\d+)$' -and $Matches[2] -eq $Suffix) {
            return "$($Matches[1])$Suffix$([int]$Matches[3] + 1)"
        }

        $StableVersion = $Current -replace '(?i)(a|b|rc)\d+$', ''
        $StableParts = $StableVersion -split '\.'
        [int]$Major = $StableParts[0]
        [int]$Minor = $StableParts[1]
        [int]$Patch = $StableParts[2]
        $Patch++
        return "$Major.$Minor.$Patch$Suffix" + "1"
    }
    
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
    Write-Host "Usage: .\release.ps1 [patch|minor|major|beta|rc|vX.Y.Z]" -ForegroundColor Red
    exit 1
}

$CurrentVersion = Get-CurrentVersion
$NewVersion = ""

if ($Arg -in @("patch", "minor", "major", "beta", "rc")) {
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
        
        if ($NewVersion -ne $CurrentVersion) {
            Write-Host "Updating $PyProjectFile from $CurrentVersion to $NewVersion..." -ForegroundColor Cyan
            $NewContent = $Content -replace 'version = ".*"', "version = ""$NewVersion"""
            Set-Content $PyProjectFile $NewContent
            
            Write-Host "Committing version bump..." -ForegroundColor Cyan
            git add $PyProjectFile
            git commit -m "chore: bump version to $NewVersion"
            git push
        }
    }
}

Write-Host "Preparing to release version $VersionTag..." -ForegroundColor Cyan

# Check if tag exists
if (git tag -l $VersionTag) {
    Write-Host "Tag $VersionTag already exists." -ForegroundColor Yellow
    $response = Read-Host "Do you want to delete the existing tag and recreate it? (y/n)"
    if ($response -eq 'y') {
        git tag -d $VersionTag
        git push origin :refs/tags/$VersionTag
        Write-Host "Deleted existing tag." -ForegroundColor Green
    }
    else {
        Write-Host "Aborting release." -ForegroundColor Red
        exit 1
    }
}

# Create tag
Write-Host "Creating tag $VersionTag..." -ForegroundColor Cyan
git tag $VersionTag
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to create tag." -ForegroundColor Red
    exit 1
}

# Push tag
Write-Host "Pushing tag to origin..." -ForegroundColor Cyan
git push origin $VersionTag
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to push tag." -ForegroundColor Red
    exit 1
}

# Create GitHub Release
Write-Host "Creating GitHub Release..." -ForegroundColor Cyan
$ReleaseArgs = @(
    $VersionTag,
    "--generate-notes",
    "--title",
    "Release $VersionTag"
)
if ($NewVersion -match '(?i)(a|b|rc)\d+$') {
    $ReleaseArgs += "--prerelease"
}
gh release create @ReleaseArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host "Release $VersionTag created successfully!" -ForegroundColor Green
    Write-Host "The GitHub Action 'Publish to PyPI' should now be running." -ForegroundColor Cyan
    Write-Host "Check status at: https://github.com/fritzprix/chess-mcp-server/actions" -ForegroundColor Gray
}
else {
    Write-Host "Failed to create GitHub release." -ForegroundColor Red
    exit 1
}
