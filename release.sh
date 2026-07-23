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

# --- Personal-account + environment config (so ./release.sh "just works") ---
GH_CONFIG_DIR_PERSONAL="$HOME/.config/gh-personal"           # personal gh, kept off the default (work) account
GH_ACCOUNT_EXPECTED="YairShachar"                            # account that owns the repo + tap
TAP_SSH_REMOTE="git@github-personal:$HOMEBREW_TAP_REPO.git"  # personal SSH alias, not `gh repo clone`
VENV_PYINSTALLER=".venv/bin/pyinstaller"                     # pyinstaller lives in the venv, not on PATH

# Route every `gh` call in this script through the personal config WITHOUT
# changing the global default account.
export GH_CONFIG_DIR="$GH_CONFIG_DIR_PERSONAL"

# Commit identity for the Homebrew tap (it lives in /tmp, outside the
# ~/data/projects includeIf that provides the personal identity).
GIT_NAME=$(git config user.name || true)
GIT_EMAIL=$(git config user.email || true)

preflight_fail() { echo -e "${YELLOW}✗ Pre-flight failed:${NC} $1" >&2; exit 1; }

preflight() {
    local branch
    branch=$(git rev-parse --abbrev-ref HEAD)
    [ "$branch" = "main" ] || preflight_fail "not on main (on '$branch')"
    git diff --quiet && git diff --cached --quiet \
        || preflight_fail "working tree has uncommitted changes — commit or stash first"
    [ -x "$VENV_PYINSTALLER" ] \
        || preflight_fail "$VENV_PYINSTALLER not found (run: .venv/bin/pip install pyinstaller)"
    command -v create-dmg >/dev/null \
        || preflight_fail "create-dmg not installed (run: brew install create-dmg)"
    gh auth status 2>/dev/null | grep -q "account $GH_ACCOUNT_EXPECTED" \
        || preflight_fail "personal gh account '$GH_ACCOUNT_EXPECTED' not active under $GH_CONFIG_DIR"
    [ -n "$GIT_NAME" ] && [ -n "$GIT_EMAIL" ] \
        || preflight_fail "git user.name/user.email not configured in this repo"
    echo -e "${GREEN}✓ Pre-flight OK${NC} (branch=main, clean tree, tools present, gh=$GH_ACCOUNT_EXPECTED)"
}

# Restore an in-progress VERSION bump if we abort before committing it, so a
# failed release never leaves VERSION dirty.
VERSION_BUMPED=0
cleanup_on_error() {
    if [ "$VERSION_BUMPED" = "1" ]; then
        echo -e "${YELLOW}Aborted — restoring VERSION from git${NC}" >&2
        git checkout -- VERSION 2>/dev/null || true
    fi
}
trap cleanup_on_error ERR
# Also restore VERSION on Ctrl-C / kill (the ERR trap doesn't fire on a signal),
# so an aborted release never leaves the working tree dirty at the bumped version.
trap 'cleanup_on_error; exit 130' INT TERM

# `./release.sh --check` runs only the read-only pre-flight, then exits.
if [ "${1:-}" = "--check" ]; then
    preflight
    echo "Dry-run pre-flight passed. Run './release.sh' to release for real."
    exit 0
fi

echo -e "${GREEN}=== Don't Forget Your Breaks Release Script ===${NC}"
echo ""

preflight
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

if git rev-parse "v$VERSION" >/dev/null 2>&1; then
    echo "Tag v$VERSION already exists. Aborting."
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
VERSION_BUMPED=1  # from here until commit, the trap restores VERSION on failure

# Build the app
echo ""
echo -e "${YELLOW}Building macOS app with PyInstaller...${NC}"
"$VENV_PYINSTALLER" "$APP_NAME.spec" --noconfirm

# Create DMG
echo ""
echo -e "${YELLOW}Creating DMG...${NC}"
cd dist
rm -f "$DMG_NAME" rw.*.dmg   # also clear any leftover read-write temp from a prior failed run
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

# create-dmg's real exit code is masked by the pipe above; verify the artifact
# exists instead. Aborts BEFORE commit/tag/push (the trap restores VERSION), so a
# failed DMG can never leave a tag+commit with no GitHub release (the v1.8.7 bug).
[ -f "dist/$DMG_NAME" ] || preflight_fail "create-dmg produced no dist/$DMG_NAME — aborting before release"

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
VERSION_BUMPED=0  # VERSION is now safely in git; nothing to roll back

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

# Always clone the tap FRESH. Reusing a /tmp checkout across releases is
# fragile: macOS periodically cleans /tmp, leaving a missing or partial repo,
# and a stale-but-valid clone can fail `git pull` and abort the release. The tap
# repo is tiny, so a fresh clone every time is cheap and immune to all of that.
rm -rf "$HOMEBREW_TAP_PATH"
# Clone via the personal SSH alias — NOT `gh repo clone`, which uses the
# default ssh key (work account) for github.com.
git clone "$TAP_SSH_REMOTE" "$HOMEBREW_TAP_PATH" \
    || preflight_fail "tap: 'git clone' failed — brew users will NOT get v$VERSION"
cd "$HOMEBREW_TAP_PATH"

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
# Explicit identity: this repo is in /tmp, outside the includeIf that sets it.
git -c user.name="$GIT_NAME" -c user.email="$GIT_EMAIL" \
    commit -m "Update dont-forget-your-breaks to v$VERSION" \
    || preflight_fail "tap: nothing committed (cask unchanged?) — check the tap"
git push origin main \
    || preflight_fail "tap: 'git push' failed — brew users will NOT get v$VERSION"

# Confirm the remote actually advanced to our commit — the tap has silently
# lagged before, so verify at the git level (not a cache-able API read).
if [ "$(git rev-parse HEAD)" != "$(git ls-remote origin main | cut -f1)" ]; then
    preflight_fail "tap: remote main != our commit after push — verify the tap manually"
fi

# Return to project directory
cd - > /dev/null

echo ""
echo -e "${GREEN}✓ Released v$VERSION${NC}"
echo "  GitHub: https://github.com/$GITHUB_REPO/releases/tag/v$VERSION"
echo "  Install: brew tap $HOMEBREW_TAP_REPO && brew install --cask dont-forget-your-breaks"
echo "  Upgrade: brew upgrade --cask dont-forget-your-breaks"
