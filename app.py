from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp
import os
import logging
import platform
import json
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Get absolute path to the directory where app.py is located
base_dir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__, static_folder=base_dir, template_folder=base_dir)
CORS(app)

# Check if running locally (for cookie support)
IS_LOCAL = platform.system() == 'Windows' or os.path.exists('/Users')

# Thread pool for async operations
executor = ThreadPoolExecutor(max_workers=3)

def extract_with_playwright(url):
    """Use Playwright browser automation to extract video info - bypasses bot detection."""
    try:
        from playwright.sync_api import sync_playwright
        logger.info("[Playwright] Starting browser-based extraction...")
        
        with sync_playwright() as p:
            # Launch headless browser
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            page = context.new_page()
            
            # Enable request interception to capture video URLs
            video_urls = []
            
            def handle_response(response):
                url = response.url
                content_type = response.headers.get('content-type', '')
                if 'video' in content_type or '.mp4' in url or '.webm' in url or 'googlevideo.com' in url:
                    video_urls.append({
                        'url': url,
                        'content_type': content_type
                    })
            
            page.on('response', handle_response)
            
            # Navigate to the video page
            logger.info(f"[Playwright] Navigating to: {url}")
            page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait for video element
            page.wait_for_timeout(3000)
            
            # Try to get video info from page
            title = page.title()
            
            # Try to extract video element src
            video_src = page.evaluate('''() => {
                const video = document.querySelector('video');
                if (video) {
                    return video.src || video.querySelector('source')?.src;
                }
                return null;
            }''')
            
            if video_src:
                video_urls.append({'url': video_src, 'content_type': 'video/mp4'})
            
            # Get thumbnail
            thumbnail = page.evaluate('''() => {
                const og = document.querySelector('meta[property="og:image"]');
                if (og) return og.content;
                const video = document.querySelector('video');
                if (video) return video.poster;
                return '';
            }''')
            
            browser.close()
            
            if video_urls:
                logger.info(f"[Playwright] SUCCESS! Found {len(video_urls)} video streams")
                # Format the results
                formats = []
                for i, v in enumerate(video_urls[:8]):
                    formats.append({
                        'quality': f'Stream {i+1}',
                        'ext': 'mp4',
                        'size': 'Stream',
                        'url': v['url']
                    })
                
                return {
                    'title': title or 'Video',
                    'thumbnail': thumbnail or '',
                    'duration': 0,
                    'uploader': 'Unknown',
                    'views': 'N/A',
                    'normal': formats[:8],
                    'audio': [],
                    'video': []
                }
            else:
                logger.warning("[Playwright] No video URLs captured")
                return None
                
    except ImportError:
        logger.warning("[Playwright] Playwright not installed, skipping browser extraction")
        return None
    except Exception as e:
        logger.error(f"[Playwright] Error: {str(e)}")
        return None


def get_video_info(url):
    """Extract video info with maximum compatibility across platforms."""
    
    logger.info(f"=" * 50)
    logger.info(f"Processing URL: {url}")
    logger.info(f"Running locally: {IS_LOCAL}")
    
    # Detect platform type
    is_youtube = 'youtube.com' in url or 'youtu.be' in url
    is_tiktok = 'tiktok.com' in url
    is_twitter = 'twitter.com' in url or 'x.com' in url
    is_instagram = 'instagram.com' in url
    is_facebook = 'facebook.com' in url or 'fb.watch' in url
    
    platform_name = "YouTube" if is_youtube else "TikTok" if is_tiktok else "Twitter" if is_twitter else "Instagram" if is_instagram else "Facebook" if is_facebook else "Other"
    logger.info(f"Detected platform: {platform_name}")
    
    # Base options - optimized for stealth
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'best',
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'socket_timeout': 30,
        'retries': 3,
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        },
        'geo_bypass': True,
    }
    
    # Platform-specific settings
    if is_youtube:
        ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': ['android', 'web'],
                'player_skip': ['webpage', 'configs'],
            }
        }
        # Use browser cookies on local machines
        if IS_LOCAL:
            logger.info("Attempting to use Chrome cookies for YouTube...")
            ydl_opts['cookiesfrombrowser'] = ('chrome',)
    
    info = None
    last_error = None
    
    # Attempt 1: Primary extraction with yt-dlp
    try:
        logger.info(f"[Attempt 1] yt-dlp primary extraction...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info:
            logger.info(f"[Attempt 1] SUCCESS! Title: {info.get('title', 'Unknown')}")
    except Exception as e:
        last_error = str(e)
        logger.warning(f"[Attempt 1] Failed: {last_error[:100]}")
    
    # Attempt 2: Try simpler options
    if not info:
        try:
            logger.info("[Attempt 2] Trying with minimal options...")
            simple_opts = {
                'quiet': True,
                'format': 'best',
                'nocheckcertificate': True,
                'socket_timeout': 30,
                'geo_bypass': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['mweb', 'android'],
                    }
                }
            }
            with yt_dlp.YoutubeDL(simple_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info:
                logger.info(f"[Attempt 2] SUCCESS!")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[Attempt 2] Failed: {last_error[:100]}")

    # Attempt 3: Use Playwright browser automation (best for bypassing bot detection)
    if not info and is_youtube:
        logger.info("[Attempt 3] Trying Playwright browser automation...")
        playwright_result = extract_with_playwright(url)
        if playwright_result:
            return playwright_result

    # Handle failure
    if not info:
        logger.error(f"All extraction attempts failed for {platform_name}")
        if is_youtube:
            return {
                "error": "YouTube is blocking this request. This is common on shared servers. Try: TikTok, Twitter/X, Instagram, or Vimeo links instead - they work great!",
                "suggestion": "Try pasting a TikTok, Vimeo, or Dailymotion link instead."
            }
        else:
            error_msg = last_error[:200] if last_error else 'Unknown error'
            return {"error": f"Could not extract from {platform_name}. Error: {error_msg}"}
    
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
    return jsonify({"status": "healthy", "playwright": True}), 200

@app.route('/analyze', methods=['POST'])
def analyze():
    url = request.json.get('url')
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    
    result = get_video_info(url)
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting VaultPro Elite on port {port}...")
    logger.info(f"Playwright browser automation: ENABLED")
    app.run(host='0.0.0.0', port=port)
