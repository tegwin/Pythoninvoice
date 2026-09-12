"""
Microsoft Graph Email Integration

Provides email sending and reading capabilities via Microsoft Graph API.
Requires Azure App Registration with Mail.Send and Mail.Read permissions.

Setup in Azure Portal:
1. Go to Azure Active Directory > App registrations > New registration
2. Name your app (e.g., "Invoice Manager Email")
3. Select "Accounts in this organizational directory only"
4. Register and note the Application (client) ID
5. Go to Certificates & secrets > New client secret
6. Note the secret value (shown only once)
7. Go to API permissions > Add permission > Microsoft Graph > Application permissions
8. Add: Mail.Send, Mail.Read, Mail.ReadWrite (optional)
9. Grant admin consent for your organization
"""

import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import json
import base64


class GraphEmailManager:
    """Microsoft Graph API email client."""
    
    GRAPH_URL = "https://graph.microsoft.com/v1.0"
    TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, sender_email: str):
        """
        Initialize Graph Email Manager.
        
        Args:
            tenant_id: Azure AD Tenant ID
            client_id: Application (Client) ID
            client_secret: Client Secret Value
            sender_email: Email address to send from (must be a valid mailbox)
        """
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.sender_email = sender_email
        self._access_token = None
        self._token_expires = None
    
    def _get_access_token(self) -> str:
        """Get or refresh OAuth2 access token."""
        # Check if we have a valid cached token
        if self._access_token and self._token_expires:
            if datetime.now() < self._token_expires - timedelta(minutes=5):
                return self._access_token
        
        # Request new token
        token_url = self.TOKEN_URL.format(tenant_id=self.tenant_id)
        
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': 'https://graph.microsoft.com/.default',
            'grant_type': 'client_credentials'
        }
        
        response = requests.post(token_url, data=data, timeout=30)
        
        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get('error_description', error_data.get('error', 'Unknown error'))
            raise Exception(f"Failed to get access token: {error_msg}")
        
        token_data = response.json()
        self._access_token = token_data['access_token']
        expires_in = token_data.get('expires_in', 3600)
        self._token_expires = datetime.now() + timedelta(seconds=expires_in)
        
        return self._access_token
    
    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        token = self._get_access_token()
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    
    def test_connection(self) -> Dict[str, Any]:
        """
        Test the Graph API connection and permissions.
        
        Returns:
            Dict with success status and user info or error message
        """
        try:
            # Get access token (tests authentication)
            self._get_access_token()
            
            # Try to access the sender's mailbox folders (tests Mail.Read permission)
            # This is better than /users/{email} which requires User.Read.All
            url = f"{self.GRAPH_URL}/users/{self.sender_email}/mailFolders/inbox"
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            
            if response.status_code == 200:
                folder_data = response.json()
                return {
                    'success': True,
                    'message': 'Connection successful',
                    'user': {
                        'displayName': self.sender_email,
                        'mail': self.sender_email,
                        'unreadCount': folder_data.get('unreadItemCount', 0)
                    }
                }
            elif response.status_code == 403:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get('error', {}).get('message', 'Permission denied')
                return {
                    'success': False,
                    'message': f'Permission denied: {error_msg}. Ensure Mail.Read permission is granted and admin consent given.'
                }
            elif response.status_code == 404:
                return {
                    'success': False,
                    'message': f'Mailbox not found: {self.sender_email}. Ensure the mailbox exists and has an Exchange Online license.'
                }
            else:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get('error', {}).get('message', response.text or 'Unknown error')
                return {
                    'success': False,
                    'message': f'API error ({response.status_code}): {error_msg}'
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': str(e)
            }
    
    def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        body_type: str = 'Text',
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        attachments: Optional[List[Dict]] = None,
        importance: str = 'normal',
        save_to_sent: bool = True
    ) -> Dict[str, Any]:
        """
        Send an email via Microsoft Graph API.
        
        Args:
            to_email: Recipient email address (or comma-separated list)
            subject: Email subject
            body: Email body content
            body_type: 'Text' or 'HTML'
            cc: List of CC email addresses
            bcc: List of BCC email addresses
            attachments: List of attachment dicts with 'name', 'content_type', 'content_bytes'
            importance: 'low', 'normal', or 'high'
            save_to_sent: Whether to save email to Sent Items folder
            
        Returns:
            Dict with success status and message
        """
        try:
            url = f"{self.GRAPH_URL}/users/{self.sender_email}/sendMail"
            
            # Build recipient list
            to_recipients = []
            for email in to_email.replace(';', ',').split(','):
                email = email.strip()
                if email:
                    to_recipients.append({
                        'emailAddress': {'address': email}
                    })
            
            # Build message
            message = {
                'subject': subject,
                'body': {
                    'contentType': body_type,
                    'content': body
                },
                'toRecipients': to_recipients,
                'importance': importance
            }
            
            # Add CC
            if cc:
                message['ccRecipients'] = [
                    {'emailAddress': {'address': email.strip()}} 
                    for email in cc if email.strip()
                ]
            
            # Add BCC
            if bcc:
                message['bccRecipients'] = [
                    {'emailAddress': {'address': email.strip()}} 
                    for email in bcc if email.strip()
                ]
            
            # Add attachments
            if attachments:
                message['attachments'] = []
                for att in attachments:
                    # Content should be base64 encoded
                    content = att.get('content_bytes', b'')
                    if isinstance(content, bytes):
                        content = base64.b64encode(content).decode('utf-8')
                    
                    message['attachments'].append({
                        '@odata.type': '#microsoft.graph.fileAttachment',
                        'name': att.get('name', 'attachment'),
                        'contentType': att.get('content_type', 'application/octet-stream'),
                        'contentBytes': content
                    })
            
            # Build request body
            request_body = {
                'message': message,
                'saveToSentItems': save_to_sent
            }
            
            # Send the email
            response = requests.post(
                url, 
                headers=self._get_headers(), 
                json=request_body,
                timeout=60
            )
            
            if response.status_code == 202:
                return {
                    'success': True,
                    'message': 'Email sent successfully'
                }
            else:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get('error', {}).get('message', response.text or 'Unknown error')
                return {
                    'success': False,
                    'message': f'Failed to send email: {error_msg}'
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f'Error sending email: {str(e)}'
            }
    
    def send_html_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Send an HTML email."""
        return self.send_email(to_email, subject, html_body, body_type='HTML', **kwargs)
    
    def get_messages(
        self,
        folder: str = 'inbox',
        top: int = 10,
        filter_query: Optional[str] = None,
        select: Optional[List[str]] = None,
        order_by: str = 'receivedDateTime desc',
        unread_only: bool = False
    ) -> Dict[str, Any]:
        """
        Get messages from a mailbox folder.
        
        Args:
            folder: Folder name ('inbox', 'sentItems', 'drafts', etc.) or folder ID
            top: Number of messages to return (max 1000)
            filter_query: OData filter query (e.g., "from/emailAddress/address eq 'someone@example.com'")
            select: List of fields to return (e.g., ['subject', 'from', 'receivedDateTime'])
            order_by: Sort order (e.g., 'receivedDateTime desc')
            unread_only: Only return unread messages
            
        Returns:
            Dict with success status and messages list
        """
        try:
            url = f"{self.GRAPH_URL}/users/{self.sender_email}/mailFolders/{folder}/messages"
            
            params = {
                '$top': min(top, 1000),
                '$orderby': order_by
            }
            
            if select:
                params['$select'] = ','.join(select)
            
            filters = []
            if unread_only:
                filters.append('isRead eq false')
            if filter_query:
                filters.append(filter_query)
            
            if filters:
                params['$filter'] = ' and '.join(filters)
            
            response = requests.get(
                url,
                headers=self._get_headers(),
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                messages = data.get('value', [])
                return {
                    'success': True,
                    'messages': messages,
                    'count': len(messages),
                    'next_link': data.get('@odata.nextLink')
                }
            else:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get('error', {}).get('message', 'Unknown error')
                return {
                    'success': False,
                    'message': f'Failed to get messages: {error_msg}',
                    'messages': []
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f'Error getting messages: {str(e)}',
                'messages': []
            }
    
    def get_message(self, message_id: str) -> Dict[str, Any]:
        """
        Get a specific message by ID.
        
        Args:
            message_id: The message ID
            
        Returns:
            Dict with success status and message data
        """
        try:
            url = f"{self.GRAPH_URL}/users/{self.sender_email}/messages/{message_id}"
            
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            
            if response.status_code == 200:
                return {
                    'success': True,
                    'message': response.json()
                }
            else:
                return {
                    'success': False,
                    'message': 'Failed to get message'
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': str(e)
            }
    
    def mark_as_read(self, message_id: str, is_read: bool = True) -> Dict[str, Any]:
        """
        Mark a message as read or unread.
        
        Args:
            message_id: The message ID
            is_read: True to mark as read, False to mark as unread
            
        Returns:
            Dict with success status
        """
        try:
            url = f"{self.GRAPH_URL}/users/{self.sender_email}/messages/{message_id}"
            
            response = requests.patch(
                url,
                headers=self._get_headers(),
                json={'isRead': is_read},
                timeout=30
            )
            
            if response.status_code == 200:
                return {'success': True, 'message': 'Message updated'}
            else:
                return {'success': False, 'message': 'Failed to update message'}
                
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def search_messages(
        self,
        search_query: str,
        top: int = 25
    ) -> Dict[str, Any]:
        """
        Search messages using KQL (Keyword Query Language).
        
        Args:
            search_query: Search string (e.g., "subject:invoice", "from:customer@example.com")
            top: Number of results to return
            
        Returns:
            Dict with success status and matching messages
        """
        try:
            url = f"{self.GRAPH_URL}/users/{self.sender_email}/messages"
            
            params = {
                '$search': f'"{search_query}"',
                '$top': min(top, 250)
            }
            
            response = requests.get(
                url,
                headers=self._get_headers(),
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'messages': data.get('value', []),
                    'count': len(data.get('value', []))
                }
            else:
                return {
                    'success': False,
                    'message': 'Search failed',
                    'messages': []
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': str(e),
                'messages': []
            }
    
    def get_mail_folders(self) -> Dict[str, Any]:
        """
        Get list of mail folders.
        
        Returns:
            Dict with success status and folders list
        """
        try:
            url = f"{self.GRAPH_URL}/users/{self.sender_email}/mailFolders"
            
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'folders': data.get('value', [])
                }
            else:
                return {
                    'success': False,
                    'message': 'Failed to get folders',
                    'folders': []
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': str(e),
                'folders': []
            }


def get_graph_email_manager(user_id: int) -> Optional[GraphEmailManager]:
    """
    Get a configured GraphEmailManager for a user.
    
    Args:
        user_id: The user ID to get settings for
        
    Returns:
        GraphEmailManager instance or None if not configured
    """
    from app_core import SettingsManager
    
    settings = SettingsManager(user_id).get_settings()
    
    tenant_id = settings.get('graph_tenant_id')
    client_id = settings.get('graph_client_id')
    client_secret = settings.get('graph_client_secret')
    sender_email = settings.get('graph_sender_email')
    
    if not all([tenant_id, client_id, client_secret, sender_email]):
        return None
    
    return GraphEmailManager(tenant_id, client_id, client_secret, sender_email)
