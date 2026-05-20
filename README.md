# linked-voyager — LinkedIn Voyager API skill for Claude Code

A self-contained Claude Code skill that exposes LinkedIn's internal **Voyager API** as CLI commands. Search people, get post likers/comments, send messages, look up companies and their employees — all programmatically, no UI clicks, no Chrome plugin needed at runtime.

Auth runs through a dedicated logged-in Brave browser profile.

---

## Setup (5 minutes)

### Prerequisites
- macOS (Linux/Windows untested)
- Python 3.10+
- [Brave browser](https://brave.com)
- A LinkedIn account
- [Claude Code](https://claude.com/claude-code) installed

### Install

```bash
git clone https://github.com/mathewdewstowe/linkedin-mcp-skills.git
cd linkedin-mcp-skills/linked-voyager
chmod +x setup.sh
./setup.sh
```

The setup script:
1. Installs Playwright + Chromium
2. Creates a dedicated Brave profile at `~/.brave-paginator/profile`
3. Registers the skill with Claude Code at `~/.claude/skills/linkedin/SKILL.md`
4. Patches paths so the skill works from your clone location

### One-time LinkedIn login

```bash
"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
  --user-data-dir=$HOME/.brave-paginator/profile
```

Log into LinkedIn once in that Brave window. Close it. The session cookie is now saved and the skill can use it indefinitely (until LinkedIn invalidates it — typically months).

### Verify

```bash
python3 main.py search-people --title "VP Sales" --1st
```

You should see your 1st-degree connections whose headlines contain "VP Sales".

---

## Usage

In any Claude Code chat, just ask LinkedIn questions naturally — `/linkedin` triggers automatically:

> "Search LinkedIn for sales directors in London, 1st degree only"
> "Who liked this post: <url>"
> "Send a LinkedIn message to Jane Doe saying hi"
> "What's Amanda Zhu been posting?"
> "Find all VPs at Recall.ai"

Claude runs `python3 main.py <command>` under the hood and parses the output.

---

## Confirmed-working commands (13)

| Command | Description |
|---|---|
| `search-people [<query>] [--1st] [--title "X"] [--title-any "A,B,C"] [--location "Y"] [--no-location]` | Search people. Default location = UK. |
| `search-posts <query>` | Search posts by keyword. |
| `post-likers <url_or_urn>` | Who liked a post. |
| `post-comments <url_or_urn>` | Comments + commenter info. |
| `profile-posts <slug_or_url> [count]` | Person's recent posts. |
| `profile-activity <slug_or_url> [count]` | All activity (posts + likes + comments + reposts). |
| `my-feed [count]` | My homepage chronological feed. |
| `company <slug>` | Company basics. |
| `company-employees <slug> [--title "X"]` | Employees at a company by title. |
| `conversations [count]` | Inbox conversations. |
| `messages <conversation_urn>` | Full message thread. |
| `send-message <conversation_urn> "<text>"` | Send to existing conversation. |
| `message-person "<name>" "<text>"` | Search person → send. |

See [`SKILL.md`](./SKILL.md) for the full command reference, examples, and architecture.

---

## How it works

```
python3 main.py <command>
        ↓
LinkedInBrowser (Playwright, headless, paginator profile)
        ↓
page.evaluate(fetch ...)   ← Voyager API call from inside the browser
        ↓
LinkedIn responds
        ↓
parsed JSON → caller
```

Voyager API endpoints used (via `page.evaluate(fetch(...))`):
- `voyagerSearchDashClusters` — people / company search
- `voyagerMessagingGraphQL/graphql` — conversations + messages
- `voyagerMessagingDashMessengerMessages` — send message
- `feed/updates/{urn}` — likers + comments
- `identity/profileUpdatesV2` — profile posts + activity
- `feed/updatesV2` — homepage feed

Cookies (`li_at`, `JSESSIONID`) come from the dedicated Brave profile — no manual token extraction.

---

## Privacy & safety

- Runs entirely on YOUR machine with YOUR LinkedIn session
- Never sends cookies anywhere except linkedin.com
- Never modifies your LinkedIn settings
- Browser is headless (invisible) — won't disturb your normal Brave usage
- Uses a SEPARATE Brave profile (`~/.brave-paginator/profile`) so it doesn't interfere with your main browser

Don't blast 500 invite requests through it — LinkedIn will rate-limit you. Treat it like a tool, not a botnet.

---

## License

MIT
