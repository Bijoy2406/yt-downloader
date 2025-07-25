#!/usr/bin/env python3
"""
YouTube Downloader Web Application
Run this script to start the web server
"""

import os
import sys

def check_dependencies():
    """Check if all required dependencies are installed"""
    try:
        import flask
        import flask_socketio
        import yt_dlp
        print("✅ All dependencies are installed")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please install dependencies using: pip install -r requirements.txt")
        return False

def create_directories():
    """Create necessary directories"""
    directories = ['downloads', 'templates']
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"📁 Created directory: {directory}")

def main():
    print("🚀 Starting YouTube Downloader Web Application")
    print("=" * 50)
    
    if not check_dependencies():
        sys.exit(1)
    
    create_directories()
    
    # Import and run the app
    from app import socketio, app
    
    print("\n🌐 Server starting...")
    print("📱 Open your browser and go to: http://localhost:5000")
    print("🛑 Press Ctrl+C to stop the server")
    print("=" * 50)
    
    try:
        socketio.run(app, debug=False, host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
    except Exception as e:
        print(f"❌ Error starting server: {e}")

if __name__ == '__main__':
    main()