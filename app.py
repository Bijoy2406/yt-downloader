from flask import Flask, render_template, request, jsonify, send_file, Response
from flask_socketio import SocketIO, emit
import yt_dlp
import os
import threading
import time
import tempfile
import shutil
from werkzeug.utils import secure_filename
import mimetypes

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Create downloads directory
DOWNLOAD_DIR = 'downloads'
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Store download info for serving files

# Store download info for serving files
download_files = {}

# Track download threads for cancellation
download_threads = {}

def progress_hook(d, socket_id):
    """Enhanced progress hook for yt-dlp"""
    try:
        if d['status'] == 'downloading':
            # Calculate progress percentage using downloaded_bytes and total_bytes
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            
            if total > 0:
                percent = (downloaded / total) * 100
            else:
                percent_str = d.get('_percent_str', '0%').replace('%', '').strip()
                try:
                    percent = float(percent_str) if percent_str != 'N/A' else 0
                except:
                    percent = 0
            
            # Format speed to include unit
            speed_bytes = d.get('speed', 0)
            if speed_bytes:
                if speed_bytes >= 1024*1024:
                    speed = f"{(speed_bytes/1024/1024):.1f} MB/s"
                else:
                    speed = f"{(speed_bytes/1024):.1f} KB/s"
            else:
                speed = d.get('_speed_str', 'N/A')
            
            # Get ETA and format it
            eta = d.get('_eta_str', 'N/A')
            if eta != 'N/A':
                try:
                    eta_secs = int(d.get('eta', 0))
                    if eta_secs > 3600:
                        eta = f"{eta_secs//3600}h {(eta_secs%3600)//60}m"
                    elif eta_secs > 60:
                        eta = f"{eta_secs//60}m {eta_secs%60}s"
                    else:
                        eta = f"{eta_secs}s"
                except:
                    pass
            
            socketio.emit('download_progress', {
                'percent': percent,
                'speed': speed,
                'eta': eta,
                'status': 'downloading'
            }, room=socket_id)
            
            # Check if download was cancelled
            cancel_flag = download_threads.get(socket_id)
            if cancel_flag and cancel_flag.is_set():
                raise Exception("Download cancelled by user")
            
        elif d['status'] == 'finished':
            filename = os.path.basename(d['filename'])
            file_path = d['filename']
            
            # Store file info for download
            download_files[socket_id] = {
                'path': file_path,
                'filename': filename,
                'ready': True
            }
            
            socketio.emit('download_progress', {
                'percent': 100,
                'status': 'finished',
                'filename': filename,
                'download_id': socket_id
            }, room=socket_id)
            
    except Exception as e:
        print(f"Progress hook error: {e}")
        if str(e) == "Download cancelled by user":
            raise

def get_video_formats(info):
    """Extract and organize video formats properly"""
    formats = info.get('formats', [])
    video_formats = []
    seen_qualities = set()
    
    print(f"Total formats found: {len(formats)}")
    
    # First pass: Get formats with both video and audio (adaptive formats)
    for f in formats:
        height = f.get('height')
        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        ext = f.get('ext', 'unknown')
        format_id = f.get('format_id', '')
        
        # Skip if no video codec or no height
        if vcodec == 'none' or not height:
            continue
            
        quality_key = f"{height}p"
        
        if quality_key not in seen_qualities:
            seen_qualities.add(quality_key)
            
            # Determine if it has audio
            has_audio = acodec != 'none'
            
            # Get file size if available
            filesize = f.get('filesize') or f.get('filesize_approx', 0)
            
            format_info = {
                'resolution': quality_key,
                'format_id': format_id,
                'ext': ext,
                'filesize': filesize,
                'fps': f.get('fps', 30),
                'vcodec': vcodec,
                'acodec': acodec,
                'has_audio': has_audio,
                'quality_label': f"{quality_key} ({ext})" + (" + audio" if has_audio else " video only"),
                'height': height
            }
            
            video_formats.append(format_info)
            print(f"Added format: {quality_key} - {format_id} - {ext} - Audio: {has_audio}")
    
    # Second pass: If we don't have many formats, look for video-only formats
    if len(video_formats) < 3:
        for f in formats:
            height = f.get('height')
            vcodec = f.get('vcodec', 'none')
            ext = f.get('ext', 'unknown')
            format_id = f.get('format_id', '')
            
            if vcodec == 'none' or not height:
                continue
                
            quality_key = f"{height}p"
            
            # Only add if we don't already have this quality
            if not any(vf['resolution'] == quality_key for vf in video_formats):
                filesize = f.get('filesize') or f.get('filesize_approx', 0)
                
                format_info = {
                    'resolution': quality_key,
                    'format_id': format_id,
                    'ext': ext,
                    'filesize': filesize,
                    'fps': f.get('fps', 30),
                    'vcodec': vcodec,
                    'acodec': f.get('acodec', 'none'),
                    'has_audio': f.get('acodec', 'none') != 'none',
                    'quality_label': f"{quality_key} ({ext})" + (" + audio" if f.get('acodec', 'none') != 'none' else " video only"),
                    'height': height
                }
                
                video_formats.append(format_info)
                print(f"Added video-only format: {quality_key} - {format_id} - {ext}")
    
    # Sort by height (quality) in descending order
    video_formats.sort(key=lambda x: x['height'], reverse=True)
    
    # Add fallback formats if still not enough options
    if len(video_formats) < 3:
        common_qualities = [2160, 1440, 1080, 720, 480, 360, 240, 144]
        for height in common_qualities:
            quality_key = f"{height}p"
            if not any(vf['resolution'] == quality_key for vf in video_formats):
                video_formats.append({
                    'resolution': quality_key,
                    'format_id': f'best[height<={height}]',
                    'ext': 'mp4',
                    'filesize': 0,
                    'fps': 30,
                    'vcodec': 'unknown',
                    'acodec': 'unknown',
                    'has_audio': True,
                    'quality_label': f"{quality_key} (mp4) - best available",
                    'height': height
                })
    
    # Re-sort after adding fallbacks
    video_formats.sort(key=lambda x: x['height'], reverse=True)
    
    print(f"Final video formats: {[vf['resolution'] for vf in video_formats]}")
    return video_formats

def get_audio_formats(info):
    """Extract and organize audio formats properly"""
    formats = info.get('formats', [])
    audio_formats = []
    seen_bitrates = set()
    
    # Get audio-only formats
    for f in formats:
        acodec = f.get('acodec', 'none')
        vcodec = f.get('vcodec', 'none')
        abr = f.get('abr')
        ext = f.get('ext', 'unknown')
        format_id = f.get('format_id', '')
        
        # Only audio formats (no video)
        if acodec == 'none' or vcodec != 'none':
            continue
            
        if abr and abr not in seen_bitrates:
            seen_bitrates.add(abr)
            
            filesize = f.get('filesize') or f.get('filesize_approx', 0)
            
            audio_formats.append({
                'quality': f"{int(abr)}kbps",
                'format_id': format_id,
                'ext': ext,
                'filesize': filesize,
                'acodec': acodec,
                'bitrate': abr
            })
    
    # Add common audio qualities if not found
    common_bitrates = [320, 256, 192, 128, 96, 64]
    for abr in common_bitrates:
        if abr not in seen_bitrates:
            audio_formats.append({
                'quality': f"{abr}kbps",
                'format_id': f'bestaudio[abr<={abr}]',
                'ext': 'mp3',
                'filesize': 0,
                'acodec': 'unknown',
                'bitrate': abr
            })
    
    # Sort by bitrate descending
    audio_formats.sort(key=lambda x: x['bitrate'], reverse=True)
    
    return audio_formats

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_info', methods=['POST'])
def get_info():
    url = request.json.get('url')
    if not url:
        return jsonify({'error': 'URL is required'})
    
    try:
        # Use more comprehensive options to get all formats
        ydl_opts = {
            'quiet': False,  # Enable output to see what's happening
            'no_warnings': False,
            'listformats': True,  # This helps get more format info
            'format': 'all',  # Get all available formats
        }
        
        print(f"Extracting info for: {url}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if 'entries' in info:
                # Playlist
                return jsonify({
                    'is_playlist': True,
                    'title': info.get('title', 'Unknown Playlist'),
                    'uploader': info.get('uploader', 'Unknown'),
                    'video_count': len([e for e in info['entries'] if e]),
                    'thumbnail': info.get('thumbnail', ''),
                })
            else:
                # Single video
                print(f"Video title: {info.get('title', 'Unknown')}")
                print(f"Total formats available: {len(info.get('formats', []))}")
                
                # Get organized formats
                video_formats = get_video_formats(info)
                audio_formats = get_audio_formats(info)
                
                # Debug: Print available heights
                available_heights = [f.get('height') for f in info.get('formats', []) if f.get('height')]
                unique_heights = sorted(set(available_heights), reverse=True)
                print(f"Available video heights: {unique_heights}")
                
                return jsonify({
                    'is_playlist': False,
                    'title': info.get('title', 'Unknown'),
                    'uploader': info.get('uploader', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'view_count': info.get('view_count', 0),
                    'video_formats': video_formats,
                    'audio_formats': audio_formats,
                    'debug_info': {
                        'total_formats': len(info.get('formats', [])),
                        'available_heights': unique_heights,
                        'max_height': max(unique_heights) if unique_heights else 0
                    }
                })
            
    except Exception as e:
        print(f"Error getting video info: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)})

@app.route('/download_file/<download_id>')
def download_file(download_id):
    """Serve the downloaded file to trigger browser download"""
    if download_id not in download_files:
        return "File not found", 404
    
    file_info = download_files[download_id]
    file_path = file_info['path']
    filename = file_info['filename']
    
    if not os.path.exists(file_path):
        return "File not found", 404
    
    # Get file size for Content-Length header
    file_size = os.path.getsize(file_path)
    
    # Determine MIME type
    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = 'application/octet-stream'
    
    def generate():
        with open(file_path, 'rb') as f:
            while True:
                data = f.read(8192)  # Read in 8KB chunks
                if not data:
                    break
                yield data
    
    # Clean up the file info after serving (delayed)
    def cleanup():
        try:
            if download_id in download_files:
                del download_files[download_id]
        except Exception as e:
            print(f"Cleanup error: {e}")
    
    # Schedule cleanup after 1 hour
    threading.Timer(3600, cleanup).start()
    
    return Response(
        generate(),
        mimetype=mime_type,
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': str(file_size),
            'Content-Type': mime_type,
            'Cache-Control': 'no-cache'
        }
    )

@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('download')
def handle_download(data):
    url = data.get('url')
    format_type = data.get('type')
    quality = data.get('quality')

    current_socket_id = request.sid

    # Cancellation flag
    cancel_flag = threading.Event()
    download_threads[current_socket_id] = cancel_flag

    def download_thread():
        try:
            timestamp = int(time.time())
            print(f"Download request - Type: {format_type}, Quality: {quality}")
            # Build yt-dlp options based on format type and quality
            if format_type == 'playlist':
                ydl_opts = {
                    'outtmpl': os.path.join(DOWNLOAD_DIR, f'{timestamp}_%(playlist_title)s/%(title)s.%(ext)s'),
                    'progress_hooks': [lambda d: progress_hook(d, current_socket_id)],
                    'ignoreerrors': True,
                    'extract_flat': False,
                }
                if quality == 'audio':
                    ydl_opts.update({
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '320',
                        }]
                    })
                else:
                    ydl_opts['format'] = 'best[height<=720]/best'
            elif format_type == 'audio':
                quality_num = quality.replace('kbps', '')
                ydl_opts = {
                    'format': f'bestaudio[abr<={quality_num}]/bestaudio/best',
                    'outtmpl': os.path.join(DOWNLOAD_DIR, f'{timestamp}_%(title)s.%(ext)s'),
                    'progress_hooks': [lambda d: progress_hook(d, current_socket_id)],
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': quality_num,
                    }],
                    'prefer_ffmpeg': True,
                }
            else:  # video
                height = quality.replace('p', '')
                format_selectors = [
                    f'bestvideo[height<={height}]+bestaudio[ext=m4a]/bestvideo[height<={height}]+bestaudio',
                    f'best[height<={height}][ext=mp4]',
                    f'best[height<={height}]',
                    f'bestvideo[height<={height}]+bestaudio/best[height<={height}]',
                    'best'
                ]
                format_string = '/'.join(format_selectors)
                print(f"Using format string: {format_string}")
                ydl_opts = {
                    'format': format_string,
                    'outtmpl': os.path.join(DOWNLOAD_DIR, f'{timestamp}_%(title)s.%(ext)s'),
                    'progress_hooks': [lambda d: progress_hook(d, current_socket_id)],
                    'merge_output_format': 'mp4',
                    'prefer_ffmpeg': True,
                    'writesubtitles': False,
                    'writeautomaticsub': False,
                }
            ydl_opts.update({
                'ignoreerrors': True,
                'no_warnings': False,
                'extract_flat': False,
                'writethumbnail': False,
                'embedsubs': False,
                'writeinfojson': False,
                'writedescription': False,
                'writecomments': False,
                'writeannotations': False,
                'socket_timeout': 30,
                'retries': 3,
            })
            print(f"Final yt-dlp options: {ydl_opts}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if format_type == 'video':
                    available_heights = [f.get('height') for f in info.get('formats', []) if f.get('height')]
                    if available_heights:
                        max_available = max(available_heights)
                        requested_height = int(height)
                        if requested_height > max_available:
                            socketio.emit('download_progress', {
                                'status': 'info',
                                'message': f'Requested {requested_height}p not available, downloading best available quality ({max_available}p)'
                            }, room=current_socket_id)
                        else:
                            socketio.emit('download_progress', {
                                'status': 'info',
                                'message': f'Downloading {requested_height}p quality'
                            }, room=current_socket_id)
                # Start actual download
                print("Starting download...")
                try:
                    if cancel_flag.is_set():
                        socketio.emit('download_cancelled', room=current_socket_id)
                        return
                    ydl.download([url])
                except Exception as e:
                    if 'Download cancelled by user' in str(e):
                        socketio.emit('download_cancelled', room=current_socket_id)
                        return
                    raise
        except Exception as e:
            print(f"Download error: {e}")
            import traceback
            traceback.print_exc()
            socketio.emit('download_error', {'error': str(e)}, room=current_socket_id)
        finally:
            # Remove thread from tracking
            if current_socket_id in download_threads:
                del download_threads[current_socket_id]

    thread = threading.Thread(target=download_thread)
    thread.daemon = True
    thread.start()
    emit('download_started', {'message': 'Download started'})

@socketio.on('cancel_download')
def handle_cancel_download():
    current_socket_id = request.sid
    cancel_flag = download_threads.get(current_socket_id)
    if cancel_flag:
        cancel_flag.set()
        socketio.emit('download_cancelled', room=current_socket_id)

@socketio.on('disconnect')
def handle_disconnect():
    print(f'Client disconnected: {request.sid}')

if __name__ == '__main__':
    print("🚀 Starting Enhanced YouTube Downloader...")
    print("📱 Open your browser and go to: http://localhost:5000")
    print("🛑 Press Ctrl+C to stop the server")
    print("\n✨ Features:")
    print("  - Detects ALL available video qualities")
    print("  - Shows highest available quality first")
    print("  - Better format detection and selection")
    print("  - Improved error handling and debugging")
    print("  - Real-time progress updates")
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)