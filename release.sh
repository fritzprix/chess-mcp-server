#!/bin/bash

VERSION=$1

if [ -z "$VERSION" ]; then
    VERSION="v0.1.0"
fi

# Ensure version starts with v
if [[ ! $VERSION == v* ]]; then
    VERSION="v$VERSION"
fi

echo -e "\033[0;36mPreparing to release version $VERSION...\033[0m"

# Check if tag exists
if git tag -l "$VERSION" | grep -q "$VERSION"; then
    echo -e "\033[0;33mTag $VERSION already exists.\033[0m"
    read -p "Do you want to delete the existing tag and recreate it? (y/n) " response
    if [ "$response" == "y" ]; then
        git tag -d "$VERSION"
        git push origin ":refs/tags/$VERSION"
        echo -e "\033[0;32mDeleted existing tag.\033[0m"
    else
        echo -e "\033[0;31mAborting release.\033[0m"
        exit 1
    fi
fi

# Create tag
echo -e "\033[0;36mCreating tag $VERSION...\033[0m"
git tag "$VERSION"
if [ $? -ne 0 ]; then
    echo -e "\033[0;31mFailed to create tag.\033[0m"
    exit 1
fi

# Push tag
echo -e "\033[0;36mPushing tag to origin...\033[0m"
git push origin "$VERSION"
if [ $? -ne 0 ]; then
    echo -e "\033[0;31mFailed to push tag.\033[0m"
    exit 1
fi

# Create GitHub Release
echo -e "\033[0;36mCreating GitHub Release...\033[0m"
gh release create "$VERSION" --generate-notes --title "Release $VERSION"

if [ $? -eq 0 ]; then
    echo -e "\033[0;32mRelease $VERSION created successfully!\033[0m"
    echo -e "\033[0;36mThe GitHub Action 'Publish to PyPI' should now be running.\033[0m"
    echo -e "\033[1;30mCheck status at: https://github.com/fritzprix/chess-mcp-server/actions\033[0m"
else
    echo -e "\033[0;31mFailed to create GitHub release.\033[0m"
    exit 1
fi
