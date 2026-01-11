from flask import Flask, render_template, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
import yt_dlp
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import os

# Get absolute path to the directory where app.py is located
base_dir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__, static_folder=base_dir, template_folder=base_dir)
CORS(app)

def get_video_info(url):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'best',
        'extract_flat': False,
        'nocheckcertificate': True,
        'ignoreerrors': True, # Changed to true to prevent hard crashes
        'logtostderr': False,
        'no_color': True,
        'no_proxy': True,
        'socket_timeout': 30, # Prevent long-hanging requests
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Sec-Fetch-Mode': 'navigate',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['mweb', 'android', 'tvhtml5'],
                'player_skip': ['webpage', 'configs'],
                'skip': ['dash', 'hls']
            }
        },
        'geo_bypass': True,
        'no_check_certificate': True,
        'prefer_insecure': True
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            # Attempt 1: Stealth Extraction
            info = ydl.extract_info(url, download=False)
            
            # Attempt 2: Fallback to TV client if needed
            if info is None:
                logger.info("Attempt 1 failed, trying TV client fallback...")
                ydl_opts['extractor_args']['youtube']['player_client'] = ['tv']
                with yt_dlp.YoutubeDL(ydl_opts) as ydl_retry:
                    info = ydl_retry.extract_info(url, download=False)

            if info is None:
                return {"error": "Bot Detection: YouTube is blocking this server's IP. This is common on shared hosting. Please try a different video or try again in a few minutes."}

            formats = info.get('formats') or []
            
            # Categorize and deduplicate formats
            normal_map = {}
            audio_map = {}
            video_map = {}

            for f in formats:
                if not f or not f.get('url'): continue
                
                ext = f.get('ext')
                res = f.get('height')
                filesize = f.get('filesize', 0)
                filesize_mb = round(filesize / (1024 * 1024), 2) if filesize else "N/A"
                
                # Normal (Video + Audio)
                if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                    q_key = f"{res}p" if res else "Unknown"
                    if q_key not in normal_map or (filesize > 0 and filesize > normal_map[q_key].get('_size_raw', 0)):
                        normal_map[q_key] = {
                            'quality': q_key, 'ext': ext, 'size': f'{filesize_mb} MB', 'url': f.get('url'), '_size_raw': filesize
                        }
                
                # Audio Only
                elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                    abr = f.get('abr', 0)
                    q_key = f'{int(abr)}kbps' if abr else 'Unknown'
                    if q_key not in audio_map or (abr > 0 and abr > audio_map[q_key].get('_abr_raw', 0)):
                        audio_map[q_key] = {
                            'quality': q_key, 'ext': ext, 'size': f'{filesize_mb} MB', 'url': f.get('url'), '_abr_raw': abr
                        }
                
                # Video Only
                elif f.get('vcodec') != 'none' and f.get('acodec') == 'none':
                    q_key = f"{res}p" if res else "Unknown"
                    if q_key not in video_map or (filesize > 0 and filesize > video_map[q_key].get('_size_raw', 0)):
                        video_map[q_key] = {
                            'quality': q_key, 'ext': ext, 'size': f'{filesize_mb} MB', 'url': f.get('url'), '_size_raw': filesize
                        }

            # Convert maps to sorted lists
            def sort_res(x):
                val = x['quality'].replace('p','').replace('kbps','')
                return int(val) if val.isdigit() else 0

            normal = sorted(normal_map.values(), key=sort_res, reverse=True)[:8]
            audio = sorted(audio_map.values(), key=sort_res, reverse=True)[:8]
            video = sorted(video_map.values(), key=sort_res, reverse=True)[:8]

            return {
                'title': info.get('title', 'Unknown Title'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown Creator'),
                'views': f"{info.get('view_count', 0):,}",
                'upload_date': info.get('upload_date', ''),
                'normal': normal,
                'audio': audio,
                'video': video
            }

            if not info:
                return {"error": "Could not extract video information. The video might be private or restricted."}

            return {
                'title': info.get('title', 'Unknown Title'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown Creator'),
                'views': f"{info.get('view_count', 0):,}",
                'upload_date': info.get('upload_date', ''),
                'normal': normal,
                'audio': audio_only,
                'video': video_only
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
