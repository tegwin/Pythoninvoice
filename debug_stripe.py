"""
Debug script to test Stripe payment verification.
Run: python debug_stripe.py <invoice_id>
"""
import sys
import json
import requests

# Add parent to path
sys.path.insert(0, '.')

from database import get_db
from stripe_integration import StripeManager, check_payment_status

def debug_stripe_payment(invoice_id):
    """Debug Stripe payment for an invoice."""
    
    # Get user_id (assuming user 1 for now)
    user_id = 1
    
    print(f"\n=== Debugging Stripe Payment for Invoice {invoice_id} ===\n")
    
    # 1. Check Stripe settings
    stripe_manager = StripeManager(user_id)
    settings = stripe_manager.get_settings()
    print(f"Stripe Enabled: {settings.get('enabled')}")
    print(f"Live Mode: {settings.get('live_mode')}")
    print(f"Test Key Set: {'Yes' if settings.get('test_secret_key') else 'No'}")
    print(f"Live Key Set: {'Yes' if settings.get('live_secret_key') else 'No'}")
    
    api_key = stripe_manager.get_api_key()
    print(f"Using API Key: {api_key[:20]}..." if api_key else "No API Key!")
    
    # 2. Check stored session
    print(f"\n--- Stored Payment Sessions ---")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, session_id, status, amount, created_at 
            FROM stripe_payment_sessions
            WHERE invoice_id = ?
            ORDER BY created_at DESC
        ''', (invoice_id,))
        sessions = cursor.fetchall()
        
        if not sessions:
            print("No payment sessions found for this invoice!")
            return
        
        for s in sessions:
            if isinstance(s, dict):
                print(f"  Session: {s['session_id'][:30]}...")
                print(f"  Status: {s['status']}")
                print(f"  Amount: {s['amount']}")
                print(f"  Created: {s['created_at']}")
            else:
                print(f"  Session: {s}")
            print()
    
    # 3. Query Stripe directly
    print(f"\n--- Querying Stripe API ---")
    session_id = sessions[0]['session_id'] if isinstance(sessions[0], dict) else sessions[0][1]
    
    try:
        response = requests.get(
            f'https://api.stripe.com/v1/checkout/sessions/{session_id}',
            auth=(api_key, ''),
            timeout=30
        )
        
        print(f"Response Status: {response.status_code}")
        
        if response.status_code == 200:
            session = response.json()
            print(f"Payment Status: {session.get('payment_status')}")
            print(f"Amount Total: {session.get('amount_total')}")
            print(f"Currency: {session.get('currency')}")
            print(f"Payment Intent: {session.get('payment_intent')}")
            print(f"Customer Email: {session.get('customer_details', {}).get('email')}")
            
            # Check metadata
            metadata = session.get('metadata', {})
            print(f"\nMetadata:")
            print(f"  invoice_id: {metadata.get('invoice_id')}")
            print(f"  user_id: {metadata.get('user_id')}")
            
            if session.get('payment_status') == 'paid':
                print("\n✅ STRIPE SAYS PAYMENT IS COMPLETE!")
            else:
                print(f"\n⚠️ Payment status is: {session.get('payment_status')}")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Error querying Stripe: {e}")
    
    # 4. Check invoice status
    print(f"\n--- Invoice Status ---")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, invoice_number, status, total, amount_paid FROM invoices WHERE id = ?',
            (invoice_id,)
        )
        inv = cursor.fetchone()
        if inv:
            if isinstance(inv, dict):
                print(f"Invoice: {inv['invoice_number']}")
                print(f"Status: {inv['status']}")
                print(f"Total: {inv['total']}")
                print(f"Amount Paid: {inv['amount_paid']}")
            else:
                print(f"Invoice data: {inv}")
    
    # 5. Try the check_payment_status function
    print(f"\n--- Running check_payment_status ---")
    try:
        success, message = check_payment_status(user_id, invoice_id)
        print(f"Success: {success}")
        print(f"Message: {message}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    # 6. Check invoice again
    print(f"\n--- Invoice Status After Check ---")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, invoice_number, status, total, amount_paid FROM invoices WHERE id = ?',
            (invoice_id,)
        )
        inv = cursor.fetchone()
        if inv:
            if isinstance(inv, dict):
                print(f"Status: {inv['status']}")
                print(f"Amount Paid: {inv['amount_paid']}")
            else:
                print(f"Invoice data: {inv}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python debug_stripe.py <invoice_id>")
        sys.exit(1)
    
    invoice_id = int(sys.argv[1])
    debug_stripe_payment(invoice_id)
