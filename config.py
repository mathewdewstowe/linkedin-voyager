"""
Configuration for LinkedIn Outbound Agent (linked-voyager)
Customize ICP, search queries, title keywords, and daily caps here.
"""

# ------------------------------------------------------------------ #
#  ICP Search queries — run against LinkedIn People search
# ------------------------------------------------------------------ #
ICP_QUERIES = [
    'VP Sales',
    'Head of Sales Enablement',
    'Sales Enablement Manager',
    'Director of RevOps',
    'VP Revenue',
    'Chief Revenue Officer',
    'Director of Sales',
    'Head of Solutions Engineering',
    'Product Marketing Manager',
]

# ------------------------------------------------------------------ #
#  ICP title keywords — filter results to only matching titles
#  Leave empty [] to queue all results from each search.
# ------------------------------------------------------------------ #
ICP_TITLE_KEYWORDS = [
    'VP Sales',
    'Vice President Sales',
    'Head of Sales',
    'Sales Enablement',
    'RevOps',
    'Revenue Operations',
    'Director of Sales',
    'Sales Director',
    'CRO',
    'Chief Revenue',
    'VP Revenue',
    'Solutions Engineering',
    'Product Marketing',
]

# ------------------------------------------------------------------ #
#  Legacy post search queries (kept for reference)
# ------------------------------------------------------------------ #
QUERIES = ICP_QUERIES  # alias

# Signal keywords to match in post text (legacy — not currently used)
SIGNAL_KEYWORDS = [
    'sales challenge', 'deal velocity', 'sales productivity',
    'sales training', 'team enablement', 'buyer engagement',
    'demo', 'qualification', 'pipeline', 'prospecting', 'outbound',
]

# ------------------------------------------------------------------ #
#  Daily action caps
# ------------------------------------------------------------------ #
DAILY_INVITE_CAP = 15              # Platform allows ~100/week, stay well under
DAILY_COMMENT_CAP = 6              # Warmth + visibility
DAILY_WITHDRAW_CAP = 20            # Clean stale invites in batch

# Invite withdrawal threshold
WITHDRAW_AFTER_DAYS = 21           # No accept in 3 weeks → withdraw

# ------------------------------------------------------------------ #
#  Throttling (randomised delays in seconds)
# ------------------------------------------------------------------ #
THROTTLE_READ_MIN = 4
THROTTLE_READ_MAX = 12
THROTTLE_WRITE_MIN = 8
THROTTLE_WRITE_MAX = 20
THROTTLE_PHASE_MIN = 300           # 5 min between agent phases
THROTTLE_PHASE_MAX = 900           # 15 min max

# ------------------------------------------------------------------ #
#  Business hours
# ------------------------------------------------------------------ #
BUSINESS_HOURS_START = 9            # 9am
BUSINESS_HOURS_END = 17             # 5pm
ACCOUNT_TIMEZONE = 'Europe/London'

# ------------------------------------------------------------------ #
#  Browser settings
# ------------------------------------------------------------------ #
BRAVE_EXE = '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'
BRAVE_PROFILE = '/Users/matthew_dewstowe/.brave-paginator/profile'

# ------------------------------------------------------------------ #
#  Database
# ------------------------------------------------------------------ #
DB_PATH = '/Users/matthew_dewstowe/Job Apply/linked-voyager.db'
