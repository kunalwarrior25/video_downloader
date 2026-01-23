from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Directory settings
base_dir = os.path.abspath(os.path.dirname(__file__))

aapp = Flask(__name__, static_folder=base_dir, template_folder=os.path.join(base_dir, 'templates'))
CORS(app)

def get_video_info(url):
    # Cookies file path (Render pe block hone se bachne ke liye)
    cookie_path = os.path.join(base_dir, 'cookies.txt')
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'best',
        'extract_flat': False,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'no_color': True,
        'no_proxy': True,
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
    }

    # Agar cookies.txt maujood hai toh use add karein
    if os.path.exists(cookie_path):
        ydl_opts['cookiefile'] = cookie_path
        logger.info("Using cookies.txt for authentication")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            
            normal, audio_only, video_only = [], [], []

            for f in formats:
                ext = f.get('ext')
                res = f.get('height')
                filesize = f.get('filesize', 0)
                filesize_mb = round(filesize / (1024 * 1024), 2) if filesize else "N/A"
                
                # Video + Audio
                if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                    normal.append({
                        'quality': f'{res}p' if res else 'Unknown',
                        'ext': ext, 'size': f'{filesize_mb} MB', 'url': f.get('url')
                    })
                # Audio Only
                elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                    abr = f.get('abr', 0)
                    audio_only.append({
                        'quality': f'{int(abr)}kbps' if abr else 'Unknown',
                        'ext': ext, 'size': f'{filesize_mb} MB', 'url': f.get('url')
                    })
                # Video Only
                elif f.get('vcodec') != 'none' and f.get('acodec') == 'none':
                    video_only.append({
                        'quality': f'{res}p' if res else 'Unknown',
                        'ext': ext, 'size': f'{filesize_mb} MB', 'url': f.get('url')
                    })

            return {
                'title': info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration'),
                'uploader': info.get('uploader', 'Unknown Creator'),
                'views': f"{info.get('view_count', 0):,}",
                'normal': sorted(normal, key=lambda x: int(x['quality'].replace('p','')) if 'p' in x['quality'] and x['quality'] != 'Unknown' else 0, reverse=True)[:8],
                'audio': sorted(audio_only, key=lambda x: int(x['quality'].replace('kbps','')) if 'kbps' in x['quality'] and x['quality'] != 'Unknown' else 0, reverse=True)[:8],
                'video': sorted(video_only, key=lambda x: int(x['quality'].replace('p','')) if 'p' in x['quality'] and x['quality'] != 'Unknown' else 0, reverse=True)[:8]
            }
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return {"error": "YouTube blocked this request. Please update cookies.txt or try a different link."}

@app.route('/')
def index():
    if os.path.exists(os.path.join(base_dir, 'index.html')):
        return send_from_directory(base_dir, 'index.html')
    return "<h1>index.html not found!</h1>", 404

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

@app.route('/analyze', methods=['POST'])
def analyze():
    url = request.json.get('url')
    if not url: return jsonify({"error": "No URL provided"}), 400
    return jsonify(get_video_info(url))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
