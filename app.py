from flask import Flask, render_template, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
import yt_dlp
import os
import logging
import platform

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get absolute path to the directory where app.py is located
base_dir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__, static_folder=base_dir, template_folder=base_dir)
CORS(app)

# Check if running locally (for cookie support)
IS_LOCAL = platform.system() == 'Windows' or os.path.exists('/Users')

def get_video_info(url):
    # Base options - maximum stealth configuration
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'best',
        'extract_flat': False,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'no_color': True,
        'socket_timeout': 45,
        'retries': 3,
        'fragment_retries': 3,
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'player_skip': ['webpage', 'configs', 'js'],
            }
        },
        'geo_bypass': True,
        'geo_bypass_country': 'US',
    }
    
    # For local development, try to use browser cookies (much more reliable)
    if IS_LOCAL:
        # Try Chrome cookies first, then Firefox, then Edge
        for browser in ['chrome', 'firefox', 'edge', 'safari']:
            try:
                ydl_opts['cookiesfrombrowser'] = (browser,)
                logger.info(f"Attempting to use {browser} cookies for authentication...")
                break
            except Exception:
                continue
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = None
            
            # Attempt 1: Standard extraction
            try:
                logger.info(f"Extracting video info from: {url}")
                info = ydl.extract_info(url, download=False)
            except Exception as e1:
                logger.warning(f"Primary extraction failed: {e1}")
            
            # Attempt 2: If failed, try with different client
            if info is None:
                logger.info("Attempting fallback extraction with iOS client...")
                ydl_opts_fallback = ydl_opts.copy()
                ydl_opts_fallback['extractor_args'] = {
                    'youtube': {
                        'player_client': ['ios', 'mweb'],
                    }
                }
                if 'cookiesfrombrowser' in ydl_opts_fallback:
                    del ydl_opts_fallback['cookiesfrombrowser']
                try:
                    with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl_retry:
                        info = ydl_retry.extract_info(url, download=False)
                except Exception as e2:
                    logger.warning(f"Fallback extraction also failed: {e2}")

            if not info:
                return {"error": "Extraction failed. YouTube may be blocking this request. Try: 1) A different video, 2) TikTok/Twitter/Instagram links work better, 3) Wait a few minutes and retry."}

            formats = info.get('formats') or []
            
            # Robust deduplication and categorization
            normal_map = {}
            audio_map = {}
            video_map = {}

            for f in formats:
                if not f or not f.get('url'): continue
                
                ext = f.get('ext', 'mp4')
                res = f.get('height')
                filesize = f.get('filesize') or f.get('filesize_approx') or 0
                filesize_mb = round(filesize / (1024 * 1024), 1) if filesize else "N/A"
                
                # Full Video (Video + Audio)
                if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                    q_key = f"{res}p" if res else "Auto"
                    if q_key not in normal_map or filesize > normal_map[q_key].get('_size', 0):
                        normal_map[q_key] = {
                            'quality': q_key, 'ext': ext, 'size': f'{filesize_mb} MB' if filesize_mb != "N/A" else "Standard", 
                            'url': f.get('url'), '_size': filesize
                        }
                
                # Audio Only
                elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                    abr = f.get('abr') or 0
                    q_key = f'{int(abr)}kbps' if abr else 'High Quality'
                    if q_key not in audio_map or abr > audio_map[q_key].get('_abr', 0):
                        audio_map[q_key] = {
                            'quality': q_key, 'ext': ext, 'size': f'{filesize_mb} MB' if filesize_mb != "N/A" else "Audio", 
                            'url': f.get('url'), '_abr': abr
                        }
                
                # Video Only (Without Audio)
                elif f.get('vcodec') != 'none' and f.get('acodec') == 'none':
                    q_key = f"{res}p" if res else "Unknown"
                    if q_key not in video_map or filesize > video_map[q_key].get('_size', 0):
                        video_map[q_key] = {
                            'quality': q_key, 'ext': ext, 'size': f'{filesize_mb} MB' if filesize_mb != "N/A" else "Video", 
                            'url': f.get('url'), '_size': filesize
                        }

            # Helper to sort by resolution or bitrate
            def sort_rank(x):
                q = x['quality'].replace('p','').replace('kbps','')
                return int(q) if q.isdigit() else 0

            # Get Top 8 for each category
            final_normal = sorted(normal_map.values(), key=sort_rank, reverse=True)[:8]
            final_audio = sorted(audio_map.values(), key=sort_rank, reverse=True)[:8]
            final_video = sorted(video_map.values(), key=sort_rank, reverse=True)[:8]

            return {
                'title': info.get('title', 'Untitled Video'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown Uploader'),
                'views': f"{info.get('view_count', 0):,}",
                'normal': final_normal,
                'audio': final_audio,
                'video': final_video
            }
        except Exception as e:
            error_msg = str(e)
            logger.error(f"yt-dlp error: {error_msg}")
            if "Sign in" in error_msg:
                return {"error": "Bot Detection: YouTube is blocking this request. Please try a different URL or try again later."}
            return {"error": f"Extraction Error: {error_msg[:100]}..."}

@app.route('/')
def index():
    # List of possible locations for index.html
    locations = [
        base_dir,
        os.path.join(base_dir, 'templates'),
        os.path.join(base_dir, 'template')
    ]
    
    for loc in locations:
        if os.path.exists(os.path.join(loc, 'index.html')):
            return send_from_directory(loc, 'index.html')
            
    return """
    <body style="background:#0f172a;color:#f8fafc;font-family:sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;">
        <h1 style="color:#ef4444">File Not Found</h1>
        <p>Could not find <b>index.html</b> in your project folders.</p>
        <p>Please ensure index.html is in: <br><code>""" + base_dir + """</code><br> or in a <code>/templates</code> folder.</p>
    </body>
    """

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

@app.route('/analyze', methods=['POST'])
def analyze():
    url = request.json.get('url')
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    
    result = get_video_info(url)
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
