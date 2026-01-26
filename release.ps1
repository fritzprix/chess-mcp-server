param (
    [string]$Version = "v0.1.0"
)

# Ensure version starts with v
if (-not $Version.StartsWith("v")) {
    $Version = "v$Version"
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
