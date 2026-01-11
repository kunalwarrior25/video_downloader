from flask import Flask, render_template, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
import yt_dlp
import os
import logging
import platform
import subprocess

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Get absolute path to the directory where app.py is located
base_dir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__, static_folder=base_dir, template_folder=base_dir)
CORS(app)

# Check if running locally (for cookie support)
IS_LOCAL = platform.system() == 'Windows' or os.path.exists('/Users')

def get_video_info(url):
    """Extract video info with maximum compatibility across platforms."""
    
    # Detect platform type
    is_youtube = 'youtube.com' in url or 'youtu.be' in url
    
    # Base options optimized for each platform
    ydl_opts = {
        'quiet': False,
        'verbose': True,
        'no_warnings': False,
        'format': 'best',
        'extract_flat': False,
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'logtostderr': False,
        'no_color': True,
        'socket_timeout': 60,
        'retries': 5,
        'fragment_retries': 5,
        'http_chunk_size': 10485760,
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        },
        'geo_bypass': True,
        'geo_bypass_country': 'US',
    }
    
    # YouTube-specific settings
    if is_youtube:
        ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': ['android', 'web'],
                'player_skip': ['webpage', 'configs'],
            }
        }
        
        # Try to use browser cookies on local machines
        if IS_LOCAL:
            logger.info("Running locally - attempting to use browser cookies...")
            for browser in ['chrome', 'firefox', 'edge', 'brave', 'opera', 'safari']:
                try:
                    test_opts = ydl_opts.copy()
                    test_opts['cookiesfrombrowser'] = (browser,)
                    test_opts['quiet'] = True
                    logger.info(f"Testing {browser} cookies...")
                    ydl_opts['cookiesfrombrowser'] = (browser,)
                    break
                except Exception as e:
                    logger.debug(f"{browser} cookies not available: {e}")
                    continue
    
    info = None
    last_error = None
    
    # Attempt 1: Primary extraction
    try:
        logger.info(f"[Attempt 1] Extracting: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        last_error = str(e)
        logger.warning(f"[Attempt 1] Failed: {last_error}")
    
    # Attempt 2: Try without cookies and with different client
    if not info and is_youtube:
        try:
            logger.info("[Attempt 2] Trying iOS/mweb client...")
            ydl_opts2 = {
                'quiet': True,
                'format': 'best',
                'nocheckcertificate': True,
                'ignoreerrors': True,
                'socket_timeout': 60,
                'geo_bypass': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios', 'mweb'],
                    }
                }
            }
            with yt_dlp.YoutubeDL(ydl_opts2) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[Attempt 2] Failed: {last_error}")
    
    # Attempt 3: Try tv_embedded client
    if not info and is_youtube:
        try:
            logger.info("[Attempt 3] Trying tv_embedded client...")
            ydl_opts3 = {
                'quiet': True,
                'format': 'best',
                'nocheckcertificate': True,
                'ignoreerrors': True,
                'socket_timeout': 60,
                'geo_bypass': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['tv_embedded'],
                    }
                }
            }
            with yt_dlp.YoutubeDL(ydl_opts3) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[Attempt 3] Failed: {last_error}")

    # Handle failure
    if not info:
        if is_youtube:
            return {
                "error": "YouTube is blocking this request. This is common on shared servers. Try: TikTok, Twitter/X, Instagram, or Facebook links instead - they work great!",
                "suggestion": "Try pasting a TikTok, Twitter, Instagram, or Facebook link instead."
            }
        else:
            return {"error": f"Could not extract video. Error: {last_error[:150] if last_error else 'Unknown error'}"}
    
    # Process formats
    formats = info.get('formats') or []
    logger.info(f"Found {len(formats)} total formats")
    
    normal_map = {}
    audio_map = {}
    video_map = {}

    for f in formats:
        if not f or not f.get('url'):
            continue
        
        url_str = f.get('url', '')
        # Skip formats that require additional fetching
        if 'manifest' in url_str.lower() or not url_str.startswith('http'):
            continue
            
        ext = f.get('ext', 'mp4')
        res = f.get('height')
        filesize = f.get('filesize') or f.get('filesize_approx') or 0
        filesize_mb = round(filesize / (1024 * 1024), 1) if filesize else None
        size_str = f'{filesize_mb} MB' if filesize_mb else "Stream"
        
        vcodec = f.get('vcodec', 'none') or 'none'
        acodec = f.get('acodec', 'none') or 'none'
        
        has_video = vcodec != 'none'
        has_audio = acodec != 'none'
        
        # Full Video (Video + Audio)
        if has_video and has_audio:
            q_key = f"{res}p" if res else "Auto"
            if q_key not in normal_map or (filesize or 0) > normal_map[q_key].get('_size', 0):
                normal_map[q_key] = {
                    'quality': q_key, 'ext': ext, 'size': size_str,
                    'url': f.get('url'), '_size': filesize or 0
                }
        
        # Audio Only
        elif has_audio and not has_video:
            abr = f.get('abr') or f.get('tbr') or 0
            q_key = f'{int(abr)}kbps' if abr else 'Audio'
            if q_key not in audio_map or (abr or 0) > audio_map[q_key].get('_abr', 0):
                audio_map[q_key] = {
                    'quality': q_key, 'ext': ext, 'size': size_str,
                    'url': f.get('url'), '_abr': abr or 0
                }
        
        # Video Only (Without Audio)
        elif has_video and not has_audio:
            q_key = f"{res}p" if res else "Video"
            if q_key not in video_map or (filesize or 0) > video_map[q_key].get('_size', 0):
                video_map[q_key] = {
                    'quality': q_key, 'ext': ext, 'size': size_str,
                    'url': f.get('url'), '_size': filesize or 0
                }

    def sort_rank(x):
        q = x['quality'].replace('p', '').replace('kbps', '').replace('k', '')
        try:
            return int(q)
        except ValueError:
            return 0

    # Get Top 8 for each category, remove internal keys
    def clean_list(items):
        result = []
        for item in items:
            clean_item = {k: v for k, v in item.items() if not k.startswith('_')}
            result.append(clean_item)
        return result

    final_normal = clean_list(sorted(normal_map.values(), key=sort_rank, reverse=True)[:8])
    final_audio = clean_list(sorted(audio_map.values(), key=sort_rank, reverse=True)[:8])
    final_video = clean_list(sorted(video_map.values(), key=sort_rank, reverse=True)[:8])

    logger.info(f"Processed: {len(final_normal)} normal, {len(final_audio)} audio, {len(final_video)} video-only")

    return {
        'title': info.get('title', 'Untitled Video'),
        'thumbnail': info.get('thumbnail', ''),
        'duration': info.get('duration') or 0,
        'uploader': info.get('uploader') or info.get('channel') or 'Unknown',
        'views': f"{info.get('view_count', 0):,}" if info.get('view_count') else "N/A",
        'normal': final_normal,
        'audio': final_audio,
        'video': final_video
    }

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
