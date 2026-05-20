"""
SQLite store for LinkedIn Outbound Agent
Manages posts, invite queue, invites sent, comments, and daily counters
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from config import DB_PATH

class LinkedVoyagerStore:
    def __init__(self):
        self.db_path = Path(DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema if not exists"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Posts found via search
        c.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY,
                author_id TEXT,
                author_name TEXT,
                author_urn TEXT,
                post_text TEXT,
                post_url TEXT,
                posted_at TIMESTAMP,
                found_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                signal_keywords TEXT,
                commented_at TIMESTAMP,
                comment_id TEXT,
                queued_at TIMESTAMP,
                status TEXT DEFAULT 'found'
            )
        ''')
        
        # Queue of authors to invite
        c.execute('''
            CREATE TABLE IF NOT EXISTS invite_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                author_id TEXT UNIQUE,
                author_name TEXT,
                author_urn TEXT,
                from_post_id TEXT,
                reason TEXT,
                queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                invited_at TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        # Invites sent
        c.execute('''
            CREATE TABLE IF NOT EXISTS invites_sent (
                id TEXT PRIMARY KEY,
                recipient_id TEXT,
                recipient_name TEXT,
                recipient_urn TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_from_post_id TEXT,
                invitation_id TEXT,
                status TEXT DEFAULT 'sent',
                response TEXT,
                response_at TIMESTAMP,
                withdrawn_at TIMESTAMP
            )
        ''')
        
        # Comments posted
        c.execute('''
            CREATE TABLE IF NOT EXISTS comments_sent (
                id TEXT PRIMARY KEY,
                post_id TEXT,
                post_author_id TEXT,
                comment_text TEXT,
                posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                comment_id TEXT,
                status TEXT DEFAULT 'posted'
            )
        ''')
        
        # Daily action counters (resets at midnight)
        c.execute('''
            CREATE TABLE IF NOT EXISTS daily_counters (
                date DATE PRIMARY KEY,
                invites_sent INTEGER DEFAULT 0,
                comments_posted INTEGER DEFAULT 0,
                withdrawals INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_post(self, post_id, author_id, author_name, author_urn, 
                 post_text, post_url, posted_at, signal_keywords):
        """Add a found post to the store"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO posts 
            (id, author_id, author_name, author_urn, post_text, post_url, 
             posted_at, signal_keywords, found_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (post_id, author_id, author_name, author_urn, post_text, 
              post_url, posted_at, json.dumps(signal_keywords)))
        conn.commit()
        conn.close()
    
    def queue_author(self, author_id, author_name, author_urn, from_post_id, reason):
        """Add author to invite queue"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT OR IGNORE INTO invite_queue 
            (author_id, author_name, author_urn, from_post_id, reason, queued_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (author_id, author_name, author_urn, from_post_id, reason))
        conn.commit()
        conn.close()
    
    def log_comment(self, comment_id, post_id, post_author_id, comment_text, comment_api_id):
        """Log a posted comment"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT INTO comments_sent 
            (id, post_id, post_author_id, comment_text, comment_id, posted_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (comment_id, post_id, post_author_id, comment_text, comment_api_id))
        
        # Mark post as commented
        c.execute('''
            UPDATE posts SET commented_at = CURRENT_TIMESTAMP, comment_id = ?
            WHERE id = ?
        ''', (comment_api_id, post_id))
        
        # Increment daily counter
        c.execute('''
            INSERT INTO daily_counters (date, comments_posted, updated_at)
            VALUES (DATE('now'), 1, CURRENT_TIMESTAMP)
            ON CONFLICT(date) DO UPDATE SET 
                comments_posted = comments_posted + 1,
                updated_at = CURRENT_TIMESTAMP
        ''')
        
        conn.commit()
        conn.close()
    
    def log_invite(self, invite_id, recipient_id, recipient_name, recipient_urn, 
                   sent_from_post_id, invitation_id):
        """Log a sent invite"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT INTO invites_sent 
            (id, recipient_id, recipient_name, recipient_urn, sent_from_post_id, 
             invitation_id, sent_at, status)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'sent')
        ''', (invite_id, recipient_id, recipient_name, recipient_urn, 
              sent_from_post_id, invitation_id))
        
        # Update queue status
        c.execute('''
            UPDATE invite_queue SET invited_at = CURRENT_TIMESTAMP, status = 'invited'
            WHERE author_id = ?
        ''', (recipient_id,))
        
        # Increment daily counter
        c.execute('''
            INSERT INTO daily_counters (date, invites_sent, updated_at)
            VALUES (DATE('now'), 1, CURRENT_TIMESTAMP)
            ON CONFLICT(date) DO UPDATE SET 
                invites_sent = invites_sent + 1,
                updated_at = CURRENT_TIMESTAMP
        ''')
        
        conn.commit()
        conn.close()
    
    def get_pending_queue(self, limit=10):
        """Get pending authors to invite"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''
            SELECT * FROM invite_queue 
            WHERE status = 'pending'
            ORDER BY queued_at ASC
            LIMIT ?
        ''', (limit,))
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_uncommented_posts(self, limit=10):
        """Get posts that haven't been commented on yet"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''
            SELECT * FROM posts 
            WHERE commented_at IS NULL
            ORDER BY posted_at DESC
            LIMIT ?
        ''', (limit,))
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_pending_invites(self):
        """Get invites sent but not yet responded to"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''
            SELECT * FROM invites_sent 
            WHERE status = 'sent' AND response IS NULL
        ''')
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_daily_counters(self, date=None):
        """Get daily action counters"""
        if date is None:
            date = datetime.now().date()
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''
            SELECT * FROM daily_counters WHERE date = ?
        ''', (date,))
        row = c.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return {
            'date': str(date),
            'invites_sent': 0,
            'comments_posted': 0,
            'withdrawals': 0
        }
    
    def get_queue_status(self):
        """Get overall queue status"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM posts')
        posts_found = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM invite_queue WHERE status = "pending"')
        pending_invites = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM invites_sent WHERE status = "sent"')
        invites_sent = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM comments_sent')
        comments_posted = c.fetchone()[0]
        
        conn.close()
        
        return {
            'posts_found': posts_found,
            'pending_invites': pending_invites,
            'invites_sent': invites_sent,
            'comments_posted': comments_posted
        }
