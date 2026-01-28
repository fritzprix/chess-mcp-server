#!/bin/bash

# Configuration
PYPROJECT_FILE="pyproject.toml"

# Functions
get_current_version() {
    grep '^version =' "$PYPROJECT_FILE" | head -1 | cut -d '"' -f 2
}

bump_version() {
    local current=$1
    local type=$2 # patch, minor, major

    local IFS='.'
    read -r major minor patch <<< "$current"

    case $type in
        patch)
            patch=$((patch + 1))
            ;;
        minor)
            minor=$((minor + 1))
            patch=0
            ;;
        major)
            major=$((major + 1))
            minor=0
            patch=0
            ;;
    esac

    echo "${major}.${minor}.${patch}"
}

# --- Main ---

ARG=$1

if [ -z "$ARG" ]; then
    echo "Usage: $0 [patch|minor|major|vX.Y.Z]"
    exit 1
fi

CURRENT_VERSION=$(get_current_version)
NEW_VERSION=""

if [[ "$ARG" == "patch" || "$ARG" == "minor" || "$ARG" == "major" ]]; then
    echo -e "\033[0;36mBumping version ($ARG) from $CURRENT_VERSION...\033[0m"
    NEW_VERSION=$(bump_version "$CURRENT_VERSION" "$ARG")
else
    NEW_VERSION=$ARG
    # Strip leading 'v' if present for pyproject.toml consistency
    NEW_VERSION="${NEW_VERSION#v}"
fi

VERSION_TAG="v$NEW_VERSION"

echo -e "\033[0;32mTarget Version: $NEW_VERSION\033[0m"
echo -e "\033[0;32mTarget Tag:     $VERSION_TAG\033[0m"

# 1. Update pyproject.toml if version changed
if [ "$NEW_VERSION" != "$CURRENT_VERSION" ]; then
    echo -e "\033[0;36mUpdating $PYPROJECT_FILE...\033[0m"
    # Use sed to replace the version line. 
    # Works on most linux/mac environments.
    sed -i "s/^version = \".*\"/version = \"$NEW_VERSION\"/" "$PYPROJECT_FILE"
    
    # 2. Commit the change
    echo -e "\033[0;36mCommitting version bump...\033[0m"
    git add "$PYPROJECT_FILE"
    git commit -m "chore: bump version to $NEW_VERSION"
    git push
fi

# 3. Check if tag exists
if git tag -l "$VERSION_TAG" | grep -q "$VERSION_TAG"; then
    echo -e "\033[0;33mTag $VERSION_TAG already exists.\033[0m"
    read -p "Do you want to delete the existing tag and recreate it? (y/n) " response
    if [ "$response" == "y" ]; then
        git tag -d "$VERSION_TAG"
        git push origin ":refs/tags/$VERSION_TAG"
        echo -e "\033[0;32mDeleted existing tag.\033[0m"
    else
        echo -e "\033[0;31mAborting release.\033[0m"
        exit 1
    fi
fi

# 4. Create tag
echo -e "\033[0;36mCreating tag $VERSION_TAG...\033[0m"
git tag "$VERSION_TAG"
if [ $? -ne 0 ]; then
    echo -e "\033[0;31mFailed to create tag.\033[0m"
    exit 1
fi

# 5. Push tag
echo -e "\033[0;36mPushing tag to origin...\033[0m"
git push origin "$VERSION_TAG"
if [ $? -ne 0 ]; then
    echo -e "\033[0;31mFailed to push tag.\033[0m"
    exit 1
fi

# 6. Create GitHub Release
echo -e "\033[0;36mCreating GitHub Release...\033[0m"
gh release create "$VERSION_TAG" --generate-notes --title "Release $VERSION_TAG"

if [ $? -eq 0 ]; then
    echo -e "\033[0;32mRelease $VERSION_TAG created successfully!\033[0m"
    echo -e "\033[0;36mThe GitHub Action 'Publish to PyPI' should now be running.\033[0m"
    echo -e "\033[1;30mCheck status at: https://github.com/fritzprix/chess-mcp-server/actions\033[0m"
else
    echo -e "\033[0;31mFailed to create GitHub release.\033[0m"
    exit 1
fi
