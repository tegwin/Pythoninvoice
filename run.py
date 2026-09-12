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
    debug = os.environ.get('DEBUG', 'True').lower() == 'true'
    
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║           Invoice Manager - Web Application               ║
╠═══════════════════════════════════════════════════════════╣
║  Starting server at http://localhost:{port}                 ║
║  Press Ctrl+C to stop                                     ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )
