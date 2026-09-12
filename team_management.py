"""
Invoice Manager - Team Management Module
Handles multi-user access with roles and permissions.
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
import json

from app_core import get_db, hash_password

# Role definitions
ROLES = {
    'owner': {
        'name': 'Owner',
        'description': 'Full access to all features',
        'permissions': ['*']  # All permissions
    },
    'admin': {
        'name': 'Administrator',
        'description': 'Full access to all features including team management',
        'permissions': ['*']  # All permissions - same as owner
    },
    'accountant': {
        'name': 'Accountant',
        'description': 'Full access to invoices, payments, and reports',
        'permissions': [
            'invoices.view', 'invoices.create', 'invoices.edit', 'invoices.send',
            'customers.view', 'customers.create', 'customers.edit',
            'products.view',
            'payments.view', 'payments.create',
            'reports.view'
        ]
    },
    'bookkeeper': {
        'name': 'Bookkeeper',
        'description': 'View-only access to invoices and payments',
        'permissions': [
            'invoices.view',
            'customers.view',
            'products.view',
            'payments.view',
            'reports.view'
        ]
    },
    'sales': {
        'name': 'Sales',
        'description': 'Create invoices and manage customers',
        'permissions': [
            'invoices.view', 'invoices.create', 'invoices.edit',
            'customers.view', 'customers.create', 'customers.edit',
            'products.view'
        ]
    },
    'viewer': {
        'name': 'Viewer',
        'description': 'Read-only access',
        'permissions': [
            'invoices.view',
            'customers.view',
            'products.view',
            'payments.view'
        ]
    }
}


class TeamManager:
    """Manages team members and permissions."""
    
    def __init__(self, owner_user_id: int):
        self.owner_user_id = owner_user_id
    
    def get_effective_user_id(self, user_id: int) -> int:
        """Get the owner user ID for data access (team members use owner's data)."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT owner_user_id FROM team_members 
                WHERE member_user_id = ? AND active = 1
            ''', (user_id,))
            row = cursor.fetchone()
            if row:
                return row['owner_user_id']
            return user_id
    
    def invite_member(self, email: str, username: str, password: str, role: str) -> Tuple[bool, str, Optional[int]]:
        """Invite a new team member."""
        if role not in ROLES or role == 'owner':
            return False, 'Invalid role', None
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Check if username exists
            cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
            if cursor.fetchone():
                return False, 'Username already exists', None
            
            try:
                # Create user account
                cursor.execute('''
                    INSERT INTO users (username, password_hash, email, role, parent_user_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', (username, hash_password(password), email, role, self.owner_user_id))
                member_user_id = cursor.lastrowid
                
                # Create team membership
                cursor.execute('''
                    INSERT INTO team_members (owner_user_id, member_user_id, role, accepted_at)
                    VALUES (?, ?, ?, ?)
                ''', (self.owner_user_id, member_user_id, role, datetime.now().isoformat()))
                
                conn.commit()
                return True, 'Team member added successfully', member_user_id
            
            except Exception as e:
                return False, str(e), None
    
    def get_team_members(self) -> List[Dict]:
        """Get all team members."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT tm.*, u.username, u.email, u.last_login, u.active as user_active
                FROM team_members tm
                JOIN users u ON tm.member_user_id = u.id
                WHERE tm.owner_user_id = ?
                ORDER BY tm.invited_at DESC
            ''', (self.owner_user_id,))
            
            members = []
            for row in cursor.fetchall():
                member = dict(row)
                member['role_info'] = ROLES.get(member['role'], ROLES['viewer'])
                members.append(member)
            return members
    
    def get_member(self, member_id: int) -> Optional[Dict]:
        """Get a specific team member."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT tm.*, u.username, u.email, u.last_login
                FROM team_members tm
                JOIN users u ON tm.member_user_id = u.id
                WHERE tm.id = ? AND tm.owner_user_id = ?
            ''', (member_id, self.owner_user_id))
            row = cursor.fetchone()
            if row:
                member = dict(row)
                member['role_info'] = ROLES.get(member['role'], ROLES['viewer'])
                return member
            return None
    
    def update_member_role(self, member_id: int, new_role: str) -> bool:
        """Update a team member's role."""
        if new_role not in ROLES or new_role == 'owner':
            return False
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE team_members SET role = ?
                WHERE id = ? AND owner_user_id = ?
            ''', (new_role, member_id, self.owner_user_id))
            
            # Also update user's role
            cursor.execute('''
                UPDATE users SET role = ?
                WHERE id = (SELECT member_user_id FROM team_members WHERE id = ?)
            ''', (new_role, member_id))
            
            conn.commit()
            return cursor.rowcount > 0
    
    def deactivate_member(self, member_id: int) -> bool:
        """Deactivate a team member."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE team_members SET active = 0
                WHERE id = ? AND owner_user_id = ?
            ''', (member_id, self.owner_user_id))
            
            # Also deactivate user
            cursor.execute('''
                UPDATE users SET active = 0
                WHERE id = (SELECT member_user_id FROM team_members WHERE id = ?)
            ''', (member_id,))
            
            conn.commit()
            return cursor.rowcount > 0
    
    def reactivate_member(self, member_id: int) -> bool:
        """Reactivate a team member."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE team_members SET active = 1
                WHERE id = ? AND owner_user_id = ?
            ''', (member_id, self.owner_user_id))
            
            cursor.execute('''
                UPDATE users SET active = 1
                WHERE id = (SELECT member_user_id FROM team_members WHERE id = ?)
            ''', (member_id,))
            
            conn.commit()
            return cursor.rowcount > 0
    
    def delete_member(self, member_id: int) -> bool:
        """Permanently delete a team member."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get member user id
            cursor.execute('''
                SELECT member_user_id FROM team_members
                WHERE id = ? AND owner_user_id = ?
            ''', (member_id, self.owner_user_id))
            row = cursor.fetchone()
            if not row:
                return False
            
            member_user_id = row['member_user_id']
            
            # Delete team membership
            cursor.execute('DELETE FROM team_members WHERE id = ?', (member_id,))
            
            # Delete user
            cursor.execute('DELETE FROM users WHERE id = ?', (member_user_id,))
            
            conn.commit()
            return True
    
    def reset_member_password(self, member_id: int, new_password: str) -> bool:
        """Reset a team member's password."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users SET password_hash = ?
                WHERE id = (
                    SELECT member_user_id FROM team_members 
                    WHERE id = ? AND owner_user_id = ?
                )
            ''', (hash_password(new_password), member_id, self.owner_user_id))
            conn.commit()
            return cursor.rowcount > 0


def get_user_role(user_id: int) -> str:
    """Get a user's role."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT role FROM users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        return row['role'] if row else 'viewer'


def get_user_permissions(user_id: int) -> List[str]:
    """Get a user's permissions based on their role."""
    role = get_user_role(user_id)
    role_info = ROLES.get(role, ROLES['viewer'])
    return role_info['permissions']


def has_permission(user_id: int, permission: str) -> bool:
    """Check if a user has a specific permission."""
    permissions = get_user_permissions(user_id)
    if '*' in permissions:
        return True
    return permission in permissions


def check_permission(permission: str):
    """Decorator to check permissions on routes."""
    from functools import wraps
    from flask import session, flash, redirect, url_for
    
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            
            if not has_permission(session['user_id'], permission):
                flash('You do not have permission to access this feature.', 'error')
                return redirect(url_for('dashboard'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def get_data_user_id(session_user_id: int) -> int:
    """Get the user ID to use for data access (handles team member access to owner data)."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Check if this user is a team member
        cursor.execute('''
            SELECT owner_user_id FROM team_members 
            WHERE member_user_id = ? AND active = 1
        ''', (session_user_id,))
        row = cursor.fetchone()
        
        if row:
            return row['owner_user_id']
        return session_user_id
