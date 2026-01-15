from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp
import os
import logging
import platform
import re

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Get absolute path to the directory where app.py is located
base_dir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__, static_folder=base_dir, template_folder=base_dir)
CORS(app)

# Check if running locally (for cookie support)
IS_LOCAL = platform.system() == 'Windows' or os.path.exists('/Users')

def extract_with_playwright(url):
    """Use Playwright browser automation to extract video info."""
    try:
        from playwright.sync_api import sync_playwright
        logger.info("[Playwright] Starting browser-based extraction...")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            page = context.new_page()
            
            # Capture all video-related network requests
            video_urls = []
            
            def handle_response(response):
                url_str = response.url
                content_type = response.headers.get('content-type', '')
                
                # Look for video streams
                if any(x in url_str for x in ['googlevideo.com', '.mp4', '.webm', 'videoplayback']):
                    # Extract quality from URL
                    quality = 'Auto'
                    if 'itag=' in url_str:
                        itag = re.search(r'itag=(\d+)', url_str)
                        if itag:
                            itag_map = {
                                '18': '360p', '22': '720p', '37': '1080p', '38': '4K',
                                '134': '360p', '135': '480p', '136': '720p', '137': '1080p',
                                '138': '4K', '160': '144p', '242': '240p', '243': '360p',
                                '244': '480p', '247': '720p', '248': '1080p', '271': '1440p',
                                '313': '2160p', '140': '128kbps', '141': '256kbps', '251': '160kbps'
                            }
                            quality = itag_map.get(itag.group(1), f'itag-{itag.group(1)}')
                    
                    video_urls.append({
                        'url': url_str,
                        'quality': quality,
                        'content_type': content_type
                    })
            
            page.on('response', handle_response)
            
            logger.info(f"[Playwright] Navigating to: {url}")
            page.goto(url, wait_until='networkidle', timeout=45000)
            
            # Wait for video to load
            page.wait_for_timeout(5000)
            
            # Try to play video to trigger more streams
            try:
                page.click('video', timeout=3000)
            except:
                pass
            
            page.wait_for_timeout(3000)
            
            # Get metadata from page
            title = page.title().replace(' - YouTube', '').strip()
            
            thumbnail = page.evaluate('''() => {
                const og = document.querySelector('meta[property="og:image"]');
                if (og) return og.content;
                const video = document.querySelector('video');
                if (video && video.poster) return video.poster;
                return '';
            }''')
            
            uploader = page.evaluate('''() => {
                const channel = document.querySelector('#channel-name a, .ytd-channel-name a, [itemprop="author"] [itemprop="name"]');
                if (channel) return channel.textContent.trim();
                const owner = document.querySelector('#owner-name a, .ytd-video-owner-renderer a');
                if (owner) return owner.textContent.trim();
                return 'Unknown';
            }''')
            
            views = page.evaluate('''() => {
                const viewEl = document.querySelector('#count .view-count, .view-count, [itemprop="interactionCount"]');
                if (viewEl) return viewEl.textContent.trim();
                return 'N/A';
            }''')
            
            duration = page.evaluate('''() => {
                const video = document.querySelector('video');
                if (video && video.duration) return Math.floor(video.duration);
                const durationEl = document.querySelector('.ytp-time-duration');
                if (durationEl) {
                    const parts = durationEl.textContent.split(':').map(Number);
                    if (parts.length === 2) return parts[0] * 60 + parts[1];
                    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
                }
                return 0;
            }''')
            
            browser.close()
            
            if video_urls:
                logger.info(f"[Playwright] SUCCESS! Found {len(video_urls)} video streams")
                
                # Deduplicate and organize formats
                seen_qualities = set()
                normal_formats = []
                audio_formats = []
                video_formats = []
                
                for v in video_urls:
                    q = v['quality']
                    if q in seen_qualities:
                        continue
                    seen_qualities.add(q)
                    
                    fmt = {
                        'quality': q,
                        'ext': 'mp4' if '.mp4' in v['url'] or 'video' in v.get('content_type', '') else 'webm',
                        'size': 'Stream',
                        'url': v['url']
                    }
                    
                    if 'kbps' in q:
                        audio_formats.append(fmt)
                    elif 'p' in q:
                        normal_formats.append(fmt)
                        video_formats.append(fmt)
                
                # Sort by quality
                def sort_quality(x):
                    q = x['quality'].replace('p', '').replace('kbps', '').replace('K', '000')
                    try:
                        return int(q)
                    except:
                        return 0
                
                normal_formats.sort(key=sort_quality, reverse=True)
                audio_formats.sort(key=sort_quality, reverse=True)
                video_formats.sort(key=sort_quality, reverse=True)
                
                return {
                    'title': title or 'Video',
                    'thumbnail': thumbnail or '',
                    'duration': duration,
                    'uploader': uploader,
                    'views': views,
                    'normal': normal_formats[:8],
                    'audio': audio_formats[:8],
                    'video': video_formats[:8]
                }
            else:
                logger.warning("[Playwright] No video URLs captured")
                return None
                
    except ImportError:
        logger.warning("[Playwright] Playwright not installed")
        return None
    except Exception as e:
        logger.error(f"[Playwright] Error: {str(e)}")
        return None


def get_video_info(url):
    """Extract video info with maximum compatibility."""
    
    logger.info(f"=" * 60)
    logger.info(f"Processing URL: {url}")
    logger.info(f"Running locally: {IS_LOCAL}")
    
    # Detect platform
    is_youtube = 'youtube.com' in url or 'youtu.be' in url
    is_tiktok = 'tiktok.com' in url
    is_twitter = 'twitter.com' in url or 'x.com' in url
    is_instagram = 'instagram.com' in url
    is_facebook = 'facebook.com' in url or 'fb.watch' in url
    
    platform_name = "YouTube" if is_youtube else "TikTok" if is_tiktok else "Twitter" if is_twitter else "Instagram" if is_instagram else "Facebook" if is_facebook else "Other"
    logger.info(f"Detected platform: {platform_name}")
    
    # Base extraction options
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'socket_timeout': 30,
        'retries': 5,
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
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
    
    # YouTube-specific settings
    if is_youtube:
        ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': ['android', 'web'],
                'player_skip': ['webpage', 'configs'],
            }
        }
        # Try browser cookies locally
        if IS_LOCAL:
            logger.info("Attempting to use browser cookies...")
            ydl_opts['cookiesfrombrowser'] = ('chrome',)
    
    info = None
    last_error = None
    
    # Attempt 1: Standard yt-dlp
    try:
        logger.info(f"[Attempt 1] yt-dlp standard extraction...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info:
            logger.info(f"[Attempt 1] SUCCESS! Title: {info.get('title', 'Unknown')}")
    except Exception as e:
        last_error = str(e)
        logger.warning(f"[Attempt 1] Failed: {last_error[:100]}")
    
    # Attempt 2: Simplified options
    if not info:
        try:
            logger.info("[Attempt 2] Trying simplified options...")
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

    # Attempt 3: Playwright browser automation
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
                "suggestion": "Try pasting a TikTok, Vimeo, or Dailymotion link."
            }
        else:
            error_msg = last_error[:200] if last_error else 'Unknown error'
            return {"error": f"Could not extract from {platform_name}. Error: {error_msg}"}
    
    # Process formats from yt-dlp
    formats = info.get('formats') or []
    logger.info(f"Found {len(formats)} total formats")
    
    normal_map = {}
    audio_map = {}
    video_map = {}

    for f in formats:
        if not f or not f.get('url'):
            continue
        
        url_str = f.get('url', '')
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
        
        # Video Only (No Audio)
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

    # Format views
    view_count = info.get('view_count')
    views_str = f"{view_count:,}" if view_count else "N/A"

    return {
        'title': info.get('title', 'Untitled Video'),
        'thumbnail': info.get('thumbnail', ''),
        'duration': info.get('duration') or 0,
        'uploader': info.get('uploader') or info.get('channel') or info.get('creator') or 'Unknown',
        'views': views_str,
        'normal': final_normal,
        'audio': final_audio,
        'video': final_video
    }

@app.route('/')
def index():
    locations = [
        base_dir,
        os.path.join(base_dir, 'templates'),
        os.path.join(base_dir, 'template')
    ]
    
    for loc in locations:
        index_path = os.path.join(loc, 'index.html')
        if os.path.exists(index_path):
            logger.info(f"Serving index.html from: {loc}")
            return send_from_directory(loc, 'index.html')
            
    return """
    <body style="background:#0f172a;color:#f8fafc;font-family:sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;">
        <h1 style="color:#ef4444">File Not Found</h1>
        <p>Could not find <b>index.html</b></p>
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
    logger.info(f"=" * 60)
    logger.info(f"🚀 VaultPro Elite starting on port {port}")
    logger.info(f"🌐 Open: http://127.0.0.1:{port}")
    logger.info(f"🤖 Playwright: Available")
    logger.info(f"=" * 60)
    app.run(host='0.0.0.0', port=port)
