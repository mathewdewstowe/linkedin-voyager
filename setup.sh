#!/usr/bin/env bash
# linked-voyager setup script — run once on a fresh machine.
# Installs Python deps, creates a dedicated Brave profile, and registers
# the skill with Claude Code so /linkedin works in any chat.

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE_DIR="$HOME/.brave-paginator/profile"
BRAVE_EXE="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
SKILL_DIR="$HOME/.claude/skills/linkedin"

echo "━━━ linked-voyager setup ━━━"
echo "Repo:           $REPO_DIR"
echo "Brave profile:  $PROFILE_DIR"
echo "Skill install:  $SKILL_DIR"
echo

# 1. Python dependencies
echo "→ Installing Playwright Python package..."
python3 -m pip install --quiet playwright

echo "→ Installing Playwright Chromium browser..."
python3 -m playwright install chromium

# 2. Brave check
if [ ! -f "$BRAVE_EXE" ]; then
  echo "❌ Brave not found at $BRAVE_EXE"
  echo "   Install Brave from https://brave.com first, then re-run setup."
  exit 1
fi

# 3. Create dedicated profile dir
mkdir -p "$PROFILE_DIR"
echo "✓ Brave profile dir ready"

# 4. Register the skill with Claude Code
mkdir -p "$SKILL_DIR"
# Substitute the absolute path of this clone into the SKILL.md template
sed "s|__REPO_DIR__|$REPO_DIR|g" "$REPO_DIR/SKILL.md" > "$SKILL_DIR/SKILL.md"
echo "✓ Skill registered at $SKILL_DIR/SKILL.md"

# 5. Patch browser.py to point to this user's home (in case clone path differs)
sed -i '' "s|/Users/matthew_dewstowe/.brave-paginator/profile|$PROFILE_DIR|g" \
  "$REPO_DIR/browser.py" 2>/dev/null || true

echo
echo "━━━ Final step: log into LinkedIn ━━━"
echo "Run this once and log into your LinkedIn account in the window that opens:"
echo
echo "  \"$BRAVE_EXE\" --user-data-dir=\"$PROFILE_DIR\""
echo
echo "After login, close Brave. Then in any Claude Code chat, /linkedin will work."
echo
echo "Test command:"
echo "  cd \"$REPO_DIR\""
echo "  python3 main.py search-people --title \"VP Sales\" --1st"
