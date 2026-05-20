# LinkedIn Voyager API Request Capture Guide

## Overview

This guide walks you through manually capturing real LinkedIn Voyager API request shapes from Chrome DevTools. These are needed to update `voyager_client.py` with exact payloads.

## Setup

1. **Open Chrome with LinkedIn logged in**
2. **Right-click → Inspect** (or F12) to open DevTools
3. **Go to Network tab**
4. **Check: Preserve log, Hide requests from extensions**

## Requests to Capture

### 1. POST Search (Post Search Agent)

**Action:** Search for content/posts

```
URL: https://www.linkedin.com/voyager/api/search/dash/clusters
Method: POST or GET
```

**Steps:**
1. Go to LinkedIn search bar
2. Type: "VP Sales" or your target query
3. Press Enter
4. In DevTools Network tab, look for `clusters` request
5. Click it → Payload tab
6. Copy the full **Request Payload** (JSON body)
7. Copy the **Response** (first few hundred bytes to see structure)

**Save as:** `capture_search_request.json` and `capture_search_response.json`

---

### 2. GET Profile (Profile Lookup)

**Action:** View someone's profile, fetch their URN

```
URL: https://www.linkedin.com/voyager/api/identity/profiles/{username}/profileView
Method: GET
```

**Steps:**
1. Visit any LinkedIn profile: https://www.linkedin.com/in/{username}/
2. In DevTools, search for `profileView` request
3. Click it
4. Copy the full **URL** (including query parameters)
5. Note the **Response** structure (look for `entityUrn` field)

**Save as:** `capture_profile_request.txt` (just the URL) and `capture_profile_response.json` (response body)

---

### 3. POST Send Invite (Connector Agent)

**Action:** Send a connection request (no note, higher accept rate)

```
URL: https://www.linkedin.com/voyager/api/growth/normInvitationsList
Method: POST
```

**Steps:**
1. Go to any profile
2. Look for **"Connect"** button (not "Follow")
3. Click **Connect** (without adding a note) — don't confirm yet, just click to trigger
4. In DevTools, find `normInvitationsList` POST request
5. Click it → **Payload** tab
6. Copy the **Request Payload** (JSON body) — this is the exact shape needed
7. Note any special fields like `trackingId`, `invitee`, etc.

**Save as:** `capture_invite_request.json` and `capture_invite_response.json`

**Important:** Make sure this is a **no-note invite** (empty message field), not one with a custom message.

---

### 4. POST Withdraw Invite (Withdrawer Agent)

**Action:** Withdraw a pending connection request

```
URL: https://www.linkedin.com/voyager/api/relationships/invitations/{invitationId}
Method: POST
```

**Steps:**
1. Go to your **Pending** invites (Profile → Manage my network → Invitations sent)
2. Hover over a pending invite, look for **"Withdraw"** option
3. Click **Withdraw** — don't confirm yet
4. In DevTools, find the invitations request
5. Copy the **Request Payload** (should include `{"action": "withdraw"}`)
6. Get the **invitationId** from the URL

**Save as:** `capture_withdraw_request.json` and `capture_withdraw_response.json`

---

### 5. POST Comment (Commenter Agent)

**Action:** Post a comment on a post/article

```
URL: https://www.linkedin.com/voyager/api/feed/normComments
Method: POST
```

**Steps:**
1. Go to any post or article
2. Click the **comment field**
3. Type a test comment
4. Before posting, open DevTools Network tab
5. Post the comment
6. Look for `normComments` POST request
7. Copy the **Request Payload** (full JSON structure)
8. Note the post ID, comment text, and any other fields

**Save as:** `capture_comment_request.json` and `capture_comment_response.json`

---

### 6. GET Me (Current User)

**Action:** Get current user's profile info and own URN

```
URL: https://www.linkedin.com/voyager/api/me
Method: GET
```

**Steps:**
1. Go to any LinkedIn page
2. In DevTools, find the `me` GET request
3. Click it → **Response** tab
4. Copy the full response (look for your own `entityUrn`, `plainId`, `miniProfile`)

**Save as:** `capture_me_response.json`

---

### 7. GET List Pending Invites (Withdrawer Agent)

**Action:** List all pending outgoing invites to check status

```
URL: https://www.linkedin.com/voyager/api/relationships/sentInvitationViewsV2
Method: GET
```

**Steps:**
1. Go to Manage Network → Invitations Sent
2. In DevTools, find `sentInvitationViewsV2` request
3. Copy the **full URL** (with any query parameters)
4. Copy the **Response** (list structure, fields for each invite)

**Save as:** `capture_pending_invites_response.json`

---

## How to Extract & Save

For each request:

```bash
# 1. Right-click request in DevTools Network tab
# 2. Copy → Copy as cURL

# 3. Save to file:
cat > ~/Job Apply/captures/capture_search_request.txt << 'EOF'
{paste cURL here}
EOF

# 4. Also save Response:
# Click Response tab → Right-click → Copy → Save to file
```

## After Capturing

Once you have all captures:

1. **Update `voyager_client.py`** with real request shapes
   - Replace template payload structures with real ones
   - Update URL parameters and query strings
   - Fix any field names or nesting

2. **Test each agent** individually:
   ```
   /linked-voyager search
   /linked-voyager comment
   /linked-voyager connect
   /linked-voyager withdraw
   ```

3. **Run full cycle:**
   ```
   /linked-voyager run --skip-hours
   ```

## Example: What to Replace in voyager_client.py

### Before (Template):
```python
payload = {
    'trackingId': self._generate_tracking_id(),
    'invitee': {
        'InviteeProfile': {
            'profileId': recipient_id
        }
    },
    'message': message_text or ''
}
```

### After (Real):
```python
# Copy exact structure from capture_invite_request.json
payload = {
    'trackingId': '...',  # From real request
    'invitee': {
        'InviteeProfile': {
            'profileId': recipient_id
        }
    },
    # ... any additional fields from real request
}
```

## Headers to Note

When capturing, also note:

1. **CSRF Token**: Usually `csrf-token` header = your `JSESSIONID` (stripped of quotes)
2. **User-Agent**: Copy exact one from your browser
3. **X-Li-Track**: Appears in headers, update if present
4. **X-Restli-Protocol-Version**: Usually `2.0.0`

## Troubleshooting

**Can't find the request?**
- Make sure Network tab was open BEFORE you clicked the button
- Check "Preserve log" is enabled
- Search for the endpoint name (e.g., `normComments`)
- Try filtering by XHR/Fetch requests only

**Request shows as pending?**
- Wait for page to fully load
- Or close DevTools briefly to let network settle
- Refresh page and try again

**Multiple similar requests?**
- Look for the one with status 200 or 201 (success)
- Ignore 4xx/5xx errors
- Ignore duplicate requests

## Once Complete

When you have all 7 captures, message me and I'll:
1. Update `voyager_client.py` with real shapes
2. Test each agent
3. Run the full orchestrator
4. Deploy skill for production use
