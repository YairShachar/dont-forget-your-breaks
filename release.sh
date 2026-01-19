#!/bin/bash
set -e

# Configuration
APP_NAME="Dont Forget Your Breaks"
DMG_NAME="DontForgetYourBreaks.dmg"
GITHUB_REPO="YairShachar/dont-forget-your-breaks"
HOMEBREW_TAP_PATH="/tmp/homebrew-tap"
HOMEBREW_TAP_REPO="YairShachar/homebrew-tap"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Don't Forget Your Breaks Release Script ===${NC}"
echo ""

# Get current version from VERSION file or default to 1.0.0
if [ -f VERSION ]; then
    CURRENT=$(cat VERSION)
else
    CURRENT="1.0.0"
fi
echo "Current version: $CURRENT"

# Find last release tag
LAST_RELEASE_TAG=$(git tag -l "v*" --sort=-v:refname | head -1)

# Suggest version based on commit messages
MAJOR=$(echo "$CURRENT" | cut -d. -f1)
MINOR=$(echo "$CURRENT" | cut -d. -f2)
PATCH=$(echo "$CURRENT" | cut -d. -f3)

if [ -n "$LAST_RELEASE_TAG" ]; then
    COMMITS=$(git log "$LAST_RELEASE_TAG"..HEAD --pretty=format:"%s" 2>/dev/null || echo "")
else
    COMMITS=$(git log --pretty=format:"%s" -20 2>/dev/null || echo "")
fi

# Analyze commits for version bump suggestion
if echo "$COMMITS" | grep -qiE "^breaking|^.*!:|BREAKING CHANGE"; then
    SUGGESTED="$((MAJOR + 1)).0.0"
    BUMP_REASON="breaking changes detected"
elif echo "$COMMITS" | grep -qiE "^feat"; then
    SUGGESTED="$MAJOR.$((MINOR + 1)).0"
    BUMP_REASON="new features detected"
else
    SUGGESTED="$MAJOR.$MINOR.$((PATCH + 1))"
    BUMP_REASON="bug fixes/improvements"
fi

echo "Suggested: $SUGGESTED ($BUMP_REASON)"
echo ""

# Ask for new version
read -p "New version [$SUGGESTED]: " VERSION
VERSION=${VERSION:-$SUGGESTED}

if [ -z "$VERSION" ]; then
    echo "No version provided. Aborting."
    exit 1
fi

# Generate release notes from commits
echo ""
echo -e "${YELLOW}Generating release notes...${NC}"

if [ -n "$LAST_RELEASE_TAG" ]; then
    echo "Changes since $LAST_RELEASE_TAG:"
    COMMITS=$(git log "$LAST_RELEASE_TAG"..HEAD --pretty=format:"- %s" 2>/dev/null || echo "")
else
    echo "Changes (first release):"
    COMMITS=$(git log --pretty=format:"- %s" -20 2>/dev/null || echo "")
fi

if [ -z "$COMMITS" ]; then
    COMMITS="- Initial release"
fi

echo "$COMMITS"
echo ""

# Allow editing release notes
NOTES_FILE=$(mktemp)
echo "$COMMITS" > "$NOTES_FILE"

read -p "Edit release notes in editor? [y/N]: " EDIT_NOTES
if [[ "$EDIT_NOTES" =~ ^[Yy]$ ]]; then
    ${EDITOR:-vim} "$NOTES_FILE"
fi

RELEASE_NOTES=$(cat "$NOTES_FILE")
rm "$NOTES_FILE"

# Update VERSION file
echo ""
echo -e "${YELLOW}Updating version to $VERSION...${NC}"
echo "$VERSION" > VERSION

# Build the app
echo ""
echo -e "${YELLOW}Building macOS app with PyInstaller...${NC}"
pyinstaller "$APP_NAME.spec" --noconfirm

# Create DMG
echo ""
echo -e "${YELLOW}Creating DMG...${NC}"
cd dist
rm -f "$DMG_NAME"
create-dmg \
    --volname "$APP_NAME" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon-size 100 \
    --icon "$APP_NAME.app" 150 190 \
    --app-drop-link 450 190 \
    --hide-extension "$APP_NAME.app" \
    "$DMG_NAME" \
    "$APP_NAME.app" \
    2>&1 | grep -v "hdiutil does not support" || true
cd ..

# Calculate SHA256
echo ""
echo -e "${YELLOW}Calculating SHA256...${NC}"
SHA256=$(shasum -a 256 "dist/$DMG_NAME" | cut -d' ' -f1)
echo "SHA256: $SHA256"

# Commit version update
echo ""
echo -e "${YELLOW}Committing changes...${NC}"
git add VERSION
git commit -m "Release v$VERSION

$RELEASE_NOTES" || echo "No changes to commit"

# Create git tag
git tag -a "v$VERSION" -m "Release v$VERSION"

# Push to GitHub
echo ""
echo -e "${YELLOW}Pushing to GitHub...${NC}"
git push origin main
git push origin "v$VERSION"

# Create GitHub release
echo ""
echo -e "${YELLOW}Creating GitHub release...${NC}"
gh release create "v$VERSION" \
    --title "v$VERSION" \
    --notes "$RELEASE_NOTES" \
    "dist/$DMG_NAME"

# Update Homebrew tap
echo ""
echo -e "${YELLOW}Updating Homebrew tap...${NC}"

# Clone or update tap repo
if [ -d "$HOMEBREW_TAP_PATH" ]; then
    cd "$HOMEBREW_TAP_PATH"
    git pull origin main
else
    gh repo clone "$HOMEBREW_TAP_REPO" "$HOMEBREW_TAP_PATH"
    cd "$HOMEBREW_TAP_PATH"
fi

# Update cask formula
cat > "Casks/dont-forget-your-breaks.rb" << EOF
cask "dont-forget-your-breaks" do
  version "$VERSION"
  sha256 "$SHA256"

  url "https://github.com/$GITHUB_REPO/releases/download/v#{version}/DontForgetYourBreaks.dmg"
  name "Don't Forget Your Breaks"
  desc "Desktop app that reminds you to take regular breaks"
  homepage "https://github.com/$GITHUB_REPO"

  app "Dont Forget Your Breaks.app"

  # Remove quarantine attribute to avoid Gatekeeper warnings
  postflight do
    system_command "/usr/bin/xattr",
                   args: ["-cr", "#{appdir}/Dont Forget Your Breaks.app"]
  end

  zap trash: [
    "~/Library/Application Support/DontForgetYourBreaks",
    "~/Library/Preferences/com.yairs.dontforgetyourbreaks.json",
  ]
end
EOF

git add -A
git commit -m "Update dont-forget-your-breaks to v$VERSION"
git push origin main

# Return to project directory
cd - > /dev/null

echo ""
echo -e "${GREEN}✓ Released v$VERSION${NC}"
echo "  GitHub: https://github.com/$GITHUB_REPO/releases/tag/v$VERSION"
echo "  Install: brew tap $HOMEBREW_TAP_REPO && brew install --cask dont-forget-your-breaks"
echo "  Upgrade: brew upgrade --cask dont-forget-your-breaks"
