import os

class Config:
    # Flask configuration
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-this'
    
    # Download configuration
    DOWNLOAD_DIR = os.environ.get('DOWNLOAD_DIR') or 'downloads'
    MAX_DOWNLOAD_SIZE = os.environ.get('MAX_DOWNLOAD_SIZE') or '1GB'  # Maximum file size
    
    # yt-dlp configuration
    YT_DLP_OPTIONS = {
        'writesubtitles': False,  # Download subtitles
        'writeautomaticsub': False,  # Download auto-generated subtitles
        'subtitleslangs': ['en'],  # Subtitle languages
        'ignoreerrors': True,  # Continue on download errors
        'no_warnings': True,  # Suppress warnings
        'extractflat': False,  # Extract flat playlist
    }
    
    # Server configuration
    HOST = os.environ.get('HOST') or '0.0.0.0'
    PORT = int(os.environ.get('PORT') or 5000)
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    # Rate limiting
    RATE_LIMIT_ENABLED = True
    MAX_DOWNLOADS_PER_HOUR = 50
    
    # File size limits (in bytes)
    MAX_VIDEO_SIZE = 3 * 1024 * 1024 * 1024  # 2GB
    MAX_AUDIO_SIZE = 500 * 1024 * 1024  # 500MB