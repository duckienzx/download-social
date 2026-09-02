from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import yt_dlp
import requests
from bs4 import BeautifulSoup
import uvicorn
import re

app = FastAPI(title="Universal Downloader")

class URLRequest(BaseModel):
    url: str

def clean_url(url: str) -> str:
    url = url.strip()
    if "youtube.com/watch" in url:
        m = re.search(r"v=([a-zA-Z0-9_-]+)", url)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    elif "tiktok.com" in url or "instagram.com" in url:
        return url.split("?")[0]
    return url

# --- 1. ENGINE TIKTOK ---
def extract_tiktok_direct(url: str):
    try:
        res = requests.post("https://www.tikwm.com/api/", data={"url": url}, timeout=12).json()
        if res.get("code") == 0:
            d = res.get("data", {})
            return {
                "status": "success",
                "title": d.get("title", "TikTok Media"),
                "thumbnail": d.get("cover"),
                "platform": "TikTok",
                "video_url": d.get("play"),
                "audio_url": d.get("music"),
                "photos": d.get("images", [])
            }
    except Exception:
        pass
    return None

# --- 2. ENGINE INSTAGRAM (PHOTO & VIDEO) ---
def extract_instagram_media(url: str):
    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=12, allow_redirects=True)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            title = "Instagram Media"
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"]

            video_url = None
            og_video = soup.find("meta", property="og:video") or soup.find("meta", property="og:video:secure_url")
            if og_video and og_video.get("content"):
                video_url = og_video["content"]

            photos = []
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                photos.append(og_image["content"])

            if video_url or photos:
                return {
                    "status": "success",
                    "title": title,
                    "thumbnail": photos[0] if photos else None,
                    "platform": "Instagram",
                    "video_url": video_url,
                    "audio_url": None,
                    "photos": photos
                }
    except Exception:
        pass
    return None

# --- 3. ENGINE FACEBOOK ---
def extract_facebook_media(url: str):
    clean_fb_url = url.replace("www.facebook.com", "mbasic.facebook.com")
    clean_fb_url = clean_fb_url.replace("web.facebook.com", "mbasic.facebook.com")
    clean_fb_url = clean_fb_url.replace("m.facebook.com", "mbasic.facebook.com")

    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    try:
        resp = requests.get(clean_fb_url, headers=headers, timeout=12, allow_redirects=True)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = "Facebook Media"
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"]

            og_video = soup.find("meta", property="og:video") or soup.find("meta", property="og:video:secure_url")
            if og_video and og_video.get("content"):
                thumb = soup.find("meta", property="og:image")
                return {
                    "status": "success",
                    "title": title,
                    "thumbnail": thumb["content"] if thumb else None,
                    "platform": "Facebook (Video)",
                    "video_url": og_video["content"],
                    "audio_url": None,
                    "photos": []
                }

            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                img_url = og_image["content"]
                if "static.xx.fbcdn.net" not in img_url:
                    return {
                        "status": "success",
                        "title": title,
                        "thumbnail": img_url,
                        "platform": "Facebook (Photo)",
                        "video_url": None,
                        "audio_url": None,
                        "photos": [img_url]
                    }
    except Exception:
        pass
    return None

# --- 4. ENGINE TỔNG QUAN (YT-DLP) ---
def extract_ytdlp_engine(url: str):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = info.get('formats', [])
        
        audio_formats = [f for f in formats if f.get('acodec') != 'none' and (f.get('vcodec') == 'none' or 'audio only' in f.get('format', '').lower())]
        audio_url = audio_formats[-1].get('url') if audio_formats else None

        video_url = info.get('url')
        if not video_url and formats:
            combined = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
            video_url = combined[-1].get('url') if combined else formats[-1].get('url')

        photos = []
        if 'entries' in info:
            for item in info['entries']:
                if item.get('url'):
                    photos.append(item.get('url'))

        return {
            "status": "success",
            "title": info.get('title', 'Unknown Media'),
            "thumbnail": info.get('thumbnail'),
            "platform": info.get('extractor_key'),
            "video_url": video_url,
            "audio_url": audio_url,
            "photos": photos
        }

# --- API ROUTE ---
@app.post("/api/extract")
async def extract_media(request: URLRequest):
    target_url = clean_url(request.url)
    
    # TikTok
    if "tiktok.com" in target_url:
        res = extract_tiktok_direct(target_url)
        if res: return res

    # Instagram
    if "instagram.com" in target_url:
        res = extract_instagram_media(target_url)
        if res: return res

    # Facebook
    if any(fb in target_url for fb in ["facebook.com", "fb.watch", "fb.com"]):
        res = extract_facebook_media(target_url)
        if res: return res

    # Nền tảng khác (YouTube, X, Threads...)
    try:
        return extract_ytdlp_engine(target_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Lỗi trích xuất: {str(e)}")

# --- GIAO DIỆN WEB ---
@app.get("/", response_class=HTMLResponse)
async def home_page():
    return """
    <!DOCTYPE html>
    <html lang="vi">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Universal Downloader</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-900 text-white min-h-screen flex items-center justify-center p-4">
        <div class="max-w-xl w-full bg-slate-800 p-8 rounded-2xl shadow-2xl border border-slate-700">
            <h1 class="text-3xl font-black text-center mb-2 bg-gradient-to-r from-blue-400 to-indigo-500 bg-clip-text text-transparent">
                Universal Downloader
            </h1>
            <p class="text-slate-400 text-center text-sm mb-6">Tải cả Video và Ảnh từ Facebook, Instagram, TikTok, YouTube...</p>

            <div class="flex gap-2 mb-6">
                <input id="urlInput" type="text" placeholder="Dán link bài viết hoặc video..." 
                       class="flex-1 bg-slate-700 border border-slate-600 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-blue-500 transition">
                <button onclick="extractLink()" id="btnSubmit" 
                        class="bg-blue-600 hover:bg-blue-500 font-semibold px-6 py-3 rounded-xl text-sm transition">
                    Xử lý
                </button>
            </div>

            <div id="resultCard" class="hidden border-t border-slate-700 pt-6">
                <img id="thumb" class="w-full h-56 object-contain rounded-xl mb-4 bg-black">
                <h3 id="mediaTitle" class="font-bold text-base line-clamp-2 mb-4"></h3>

                <div class="flex flex-col gap-3" id="actionButtons">
                    <a id="btnVideo" target="_blank" class="hidden w-full bg-emerald-600 hover:bg-emerald-500 text-center py-2.5 rounded-lg font-medium text-sm transition">
                        🎬 Tải Video (.MP4)
                    </a>
                    <a id="btnAudio" target="_blank" class="hidden w-full bg-amber-600 hover:bg-amber-500 text-center py-2.5 rounded-lg font-medium text-sm transition">
                        🎵 Tải Âm Thanh (.MP3/M4A)
                    </a>
                </div>

                <!-- Danh sách ảnh nếu là bài viết ảnh / album -->
                <div id="photosSection" class="hidden mt-4 pt-4 border-t border-slate-700/60">
                    <p class="text-sm font-semibold text-slate-300 mb-2">🖼️ Danh sách ảnh:</p>
                    <div id="photosList" class="flex flex-col gap-2"></div>
                </div>
            </div>

            <p id="errorMsg" class="hidden mt-4 text-sm text-red-400 text-center bg-red-950/40 border border-red-800 p-3 rounded-xl"></p>
        </div>

        <script>
            async function extractLink() {
                const url = document.getElementById('urlInput').value.trim();
                const btn = document.getElementById('btnSubmit');
                const resCard = document.getElementById('resultCard');
                const errorMsg = document.getElementById('errorMsg');
                const photosSection = document.getElementById('photosSection');
                const photosList = document.getElementById('photosList');

                if(!url) return alert('Vui lòng dán liên kết!');

                btn.disabled = true;
                btn.innerText = 'Đang xử lý...';
                resCard.classList.add('hidden');
                errorMsg.classList.add('hidden');
                photosSection.classList.add('hidden');
                photosList.innerHTML = '';

                try {
                    const res = await fetch('/api/extract', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ url })
                    });
                    const json = await res.json();
                    if(!res.ok) throw new Error(json.detail || 'Không thể bóc tách URL');

                    document.getElementById('mediaTitle').innerText = json.title;
                    if(json.thumbnail) {
                        document.getElementById('thumb').src = json.thumbnail;
                        document.getElementById('thumb').classList.remove('hidden');
                    }

                    const btnVideo = document.getElementById('btnVideo');
                    const btnAudio = document.getElementById('btnAudio');

                    btnVideo.classList.toggle('hidden', !json.video_url);
                    if(json.video_url) btnVideo.href = json.video_url;

                    btnAudio.classList.toggle('hidden', !json.audio_url);
                    if(json.audio_url) btnAudio.href = json.audio_url;

                    if(json.photos && json.photos.length > 0) {
                        photosSection.classList.remove('hidden');
                        json.photos.forEach((imgUrl, index) => {
                            const link = document.createElement('a');
                            link.href = imgUrl;
                            link.target = '_blank';
                            link.className = 'w-full bg-blue-600 hover:bg-blue-500 text-center py-2 rounded-lg font-medium text-xs transition block';
                            link.innerText = `Tải ảnh ${index + 1} (.JPG)`;
                            photosList.appendChild(link);
                        });
                    }

                    resCard.classList.remove('hidden');
                } catch (err) {
                    errorMsg.innerText = err.message;
                    errorMsg.classList.remove('hidden');
                } finally {
                    btn.disabled = false;
                    btn.innerText = 'Xử lý';
                }
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
