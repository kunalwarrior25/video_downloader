from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os, uuid, threading, time, re

app = Flask(__name__)
CORS(app)

DOWNLOAD_FOLDER = '/tmp/downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

def cleanup():
    while True:
        time.sleep(300)
        for f in os.listdir(DOWNLOAD_FOLDER):
            path = os.path.join(DOWNLOAD_FOLDER, f)
            if os.path.getmtime(path) < time.time() - 300:
                try: os.remove(path)
                except: pass

threading.Thread(target=cleanup, daemon=True).start()

def sanitize(name):
    return re.sub(r'[\\/*?:"<>|]', '', name)[:100]

@app.route('/')
def home():
    return jsonify({'status': 'VidGrab API Running', 'endpoints': ['/api/info', '/api/download']})

@app.route('/api/info', methods=['POST'])
def get_info():
    url = request.json.get('url')
    if not url:
        return jsonify({'error': 'URL required'}), 400
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({
                'title': info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration'),
                'uploader': info.get('uploader'),
                'view_count': info.get('view_count'),
                'like_count': info.get('like_count')
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download():
    url = request.json.get('url')
    fmt = request.json.get('format', '720p')
    file_id = str(uuid.uuid4())
    out = os.path.join(DOWNLOAD_FOLDER, file_id)
    
    # Audio formats
    if fmt.startswith('mp3'):
        br = fmt.split('-')[1] if '-' in fmt else '192'
        opts = {'format': 'bestaudio', 'outtmpl': out+'.%(ext)s',
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': br}]}
    elif fmt == 'm4a':
        opts = {'format': 'bestaudio[ext=m4a]/bestaudio', 'outtmpl': out+'.%(ext)s'}
    # Video only (no audio)
    elif fmt.startswith('video-'):
        q = fmt.replace('video-','').replace('p','')
        opts = {'format': f'bestvideo[height<={q}]', 'outtmpl': out+'.%(ext)s'}
    # Video + Audio
    else:
        q = fmt.replace('p','')
        opts = {'format': f'bestvideo[height<={q}]+bestaudio/best[height<={q}]/best',
                'outtmpl': out+'.%(ext)s', 'merge_output_format': 'mp4'}
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url)
            for f in os.listdir(DOWNLOAD_FOLDER):
                if f.startswith(file_id):
                    ext = f.split('.')[-1]
                    name = sanitize(info.get('title','video')) + '.' + ext
                    return send_file(os.path.join(DOWNLOAD_FOLDER,f), as_attachment=True, download_name=name)
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))