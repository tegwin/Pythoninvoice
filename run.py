#!/usr/bin/env python3
"""
Invoice Manager - Application Runner
Run this script to start the web application.
"""

import os
import sys

# Ensure we're in the correct directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Import and run the Flask app
from app_web import app

if __name__ == '__main__':
    # Get port from environment or default to 5000
    port = int(os.environ.get('PORT', 5000))
    # Debug puts an interactive console on every error page, so it is opt-in
    # rather than the default, and the bind address is loopback unless asked.
    debug = os.environ.get('DEBUG', '').lower() in ('1', 'true', 'yes')
    host = os.environ.get('HOST', '127.0.0.1')
    
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║           Invoice Manager - Web Application               ║
╠═══════════════════════════════════════════════════════════╣
║  Starting server at http://{host}:{port}                 ║
║  Press Ctrl+C to stop                                     ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    app.run(
        host=host,
        port=port,
        debug=debug
    )
