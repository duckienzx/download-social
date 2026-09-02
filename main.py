from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
import yt_dlp
import requests
from bs4 import BeautifulSoup
import json
import re
import os
from pathlib import Path

app = FastAPI(title="Universal Downloader")

def clean_url(url: str) -> str:
    url = url.strip()
    if "youtube.com" in url or "youtu.be" in url:
        url = url.split("&list=")[0].split("?list=")[0]
        m = re.search(r"v=([a-zA-Z0-9_-]+)", url)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    elif "tiktok.com" in url or "instagram.com" in url:
        return url.split("?")[0]
    return url

# --- 1. TIKTOK ENGINE ---
def extract_tiktok_direct(url: str):
    try:
        res = requests.post("https://www.tikwm.com/api/", data={"url": url}, timeout=12).json()
        if res.get("code") == 0:
            d = res.get("data", {})
            formats = []
            if d.get("hdplay"):
                formats.append({"quality": "HD (Gốc)", "url": d.get("hdplay"), "ext": "mp4"})
            if d.get("play"):
                formats.append({"quality": "SD (Tiêu chuẩn)", "url": d.get("play"), "ext": "mp4"})

            return {
                "status": "success",
                "title": d.get("title", "TikTok Media"),
                "thumbnail": d.get("cover"),
                "duration": d.get("duration"),
                "platform": "TikTok",
                "video_formats": formats,
                "audio_url": d.get("music"),
                "photos": d.get("images", [])
            }
    except Exception:
        pass
    return None

# --- 2. INSTAGRAM ENGINE ---
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

            formats = [{"quality": "HD Gốc", "url": video_url, "ext": "mp4"}] if video_url else []

            if video_url or photos:
                return {
                    "status": "success",
                    "title": title,
                    "thumbnail": photos[0] if photos else None,
                    "platform": "Instagram",
                    "video_formats": formats,
                    "audio_url": None,
                    "photos": photos
                }
    except Exception:
        pass
    return None

# --- 3. FACEBOOK ENGINE ---
def extract_facebook_media(url: str):
    if any(reels_tag in url for reels_tag in ["/reel", "/share/r/", "watch", "videos"]):
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
                    'Accept-Language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
                }
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                formats = info.get('formats', [])
                video_formats = []
                seen_res = set()

                for f in reversed(formats):
                    v_url = f.get('url')
                    height = f.get('height') or 'HD'
                    format_note = f.get('format_note') or f"{height}p"
                    if v_url and format_note not in seen_res and f.get('vcodec') != 'none':
                        seen_res.add(format_note)
                        video_formats.append({
                            "quality": f"{format_note}",
                            "url": v_url,
                            "ext": "mp4"
                        })

                if not video_formats and info.get('url'):
                    video_formats.append({"quality": "Gốc (MP4)", "url": info.get('url'), "ext": "mp4"})

                if video_formats:
                    return {
                        "status": "success",
                        "title": info.get('title', 'Facebook Reel / Video'),
                        "thumbnail": info.get('thumbnail'),
                        "duration": info.get('duration'),
                        "platform": "Facebook (Video)",
                        "video_formats": video_formats[:3],
                        "audio_url": None,
                        "photos": []
                    }
        except Exception:
            pass

    session = requests.Session()
    session.headers.update({
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        resp = session.get(url, timeout=10, allow_redirects=True)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = "Facebook Post"
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"]

            thumb = soup.find("meta", property="og:image")
            thumb_url = thumb["content"] if (thumb and thumb.get("content")) else None

            if thumb_url and "static.xx.fbcdn.net" not in thumb_url:
                return {
                    "status": "success",
                    "title": title,
                    "thumbnail": thumb_url,
                    "platform": "Facebook (Photo)",
                    "video_formats": [],
                    "audio_url": None,
                    "photos": [thumb_url]
                }
    except Exception:
        pass
    return None

# --- 4. YOUTUBE & ENGINE KHÁC ---
def extract_ytdlp_engine(url: str):
    if "youtube.com" in url or "youtu.be" in url:
        url = url.split("&list=")[0].split("?list=")[0]

    BASE_DIR = Path(__file__).resolve().parent
    cookie_path = str(BASE_DIR / "cookies.txt")
    
    if not os.path.exists(cookie_path):
        cookie_path = None 

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'cookiefile': cookie_path,
        'extractor_args': {
            'youtube': {
                'player_client': ['tv_embedded', 'ios', 'mweb']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept-Language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = info.get('formats', [])
        
        audio_formats = [f for f in formats if f.get('acodec') != 'none' and (f.get('vcodec') == 'none' or 'audio' in f.get('format', '').lower())]
        audio_url = audio_formats[-1].get('url') if audio_formats else None

        seen_res = set()
        video_list = []
        for f in reversed(formats):
            height = f.get('height')
            v_url = f.get('url')
            if height and v_url and height not in seen_res and f.get('vcodec') != 'none':
                seen_res.add(height)
                video_list.append({
                    "quality": f"{height}p",
                    "url": v_url,
                    "ext": f.get('ext', 'mp4')
                })

        video_list.sort(key=lambda x: int(re.sub(r'\D', '', x['quality']) or 0), reverse=True)

        return {
            "status": "success",
            "title": info.get('title', 'Unknown Media'),
            "thumbnail": info.get('thumbnail'),
            "duration": info.get('duration'),
            "platform": info.get('extractor_key', 'YouTube'),
            "video_formats": video_list[:5],
            "audio_url": audio_url,
            "photos": []
        }

HTML_CONTENT = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Universal Media Downloader</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Plus Jakarta Sans', sans-serif; }
        .glass {
            background: rgba(15, 23, 42, 0.75);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
    </style>
</head>
<body class="bg-[#0b0f19] text-slate-100 min-h-screen flex flex-col items-center justify-between p-4 sm:p-6 selection:bg-blue-600">
    <header class="w-full max-w-3xl flex justify-between items-center py-4">
        <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-blue-500/20">
                <i class="fa-solid fa-bolt text-white text-lg"></i>
            </div>
            <span class="font-extrabold text-xl tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">MediaDownloader</span>
        </div>
        <div class="flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold px-3 py-1.5 rounded-full">
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            Server Sẵn Sàng
        </div>
    </header>

    <main class="w-full max-w-2xl my-auto">
        <div class="text-center mb-8">
            <h1 class="text-3xl sm:text-5xl font-extrabold tracking-tight mb-3">
                Tải Video, Âm Thanh & Ảnh
            </h1>
            <p class="text-slate-400 text-sm sm:text-base">Tự động nhận diện mạng xã hội & tùy chọn chất lượng video</p>
        </div>

        <div class="glass p-3 sm:p-4 rounded-2xl shadow-2xl border border-slate-800 focus-within:border-blue-500/50 transition-all duration-300 mb-6">
            <div class="flex items-center gap-3">
                <div id="platformIcon" class="w-10 h-10 rounded-xl bg-slate-800 flex items-center justify-center text-slate-400 text-lg transition-all duration-300">
                    <i class="fa-solid fa-link"></i>
                </div>
                
                <input id="urlInput" type="text" oninput="detectPlatform(this.value)" placeholder="Dán link Facebook, TikTok, Instagram hoặc YouTube..." 
                       class="flex-1 bg-transparent border-none text-slate-100 placeholder-slate-500 text-sm sm:text-base focus:outline-none">
                
                <button onclick="extractLink()" id="btnSubmit" 
                        class="bg-blue-600 hover:bg-blue-500 active:scale-95 text-white font-semibold px-5 sm:px-6 py-3 rounded-xl text-sm transition flex items-center gap-2 shrink-0 shadow-lg shadow-blue-600/30">
                    <span id="btnText">Xử Lý</span>
                    <i id="btnIcon" class="fa-solid fa-arrow-right text-xs"></i>
                </button>
            </div>
        </div>

        <div id="errorBox" class="hidden mb-6 p-4 rounded-xl bg-red-950/40 border border-red-800 text-red-300 text-sm flex items-center gap-3">
            <i class="fa-solid fa-circle-exclamation text-red-400 text-lg"></i>
            <span id="errorMsg">Đã xảy ra lỗi</span>
        </div>

        <div id="resultCard" class="hidden glass rounded-3xl p-6 shadow-2xl border border-slate-800 transition-all">
            <div class="flex flex-col sm:flex-row gap-5 items-start mb-6">
                <img id="mediaThumb" class="w-full sm:w-40 h-40 object-cover rounded-2xl bg-slate-900 border border-slate-800">
                <div class="flex-1">
                    <div class="flex items-center gap-2 mb-2">
                        <span id="platformTag" class="text-[11px] font-bold tracking-wider px-2.5 py-1 rounded-md uppercase bg-blue-500/20 text-blue-400 border border-blue-500/30">
                            Nền tảng
                        </span>
                    </div>
                    <h3 id="mediaTitle" class="font-bold text-base sm:text-lg text-slate-100 line-clamp-2 leading-snug mb-3"></h3>
                    <p class="text-xs text-slate-400"><i class="fa-regular fa-clock mr-1"></i>Đã trích xuất thành công</p>
                </div>
            </div>

            <div id="audioSection" class="hidden mb-5">
                <p class="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                    <i class="fa-solid fa-music text-amber-400"></i> Âm Thanh Gốc
                </p>
                <button id="btnAudio" class="w-full bg-slate-800/80 hover:bg-slate-700/80 border border-slate-700 p-3 rounded-xl flex items-center justify-between text-sm transition font-medium text-amber-400">
                    <span class="flex items-center gap-2"><i class="fa-solid fa-file-audio"></i> Tải Âm Thanh (MP3 / Audio)</span>
                    <i class="fa-solid fa-download"></i>
                </button>
            </div>

            <div id="videoSection" class="hidden mb-5">
                <p class="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                    <i class="fa-solid fa-video text-emerald-400"></i> Video MP4 (Chọn chất lượng)
                </p>
                <div id="videoFormatsList" class="flex flex-col gap-2"></div>
            </div>

            <div id="photoSection" class="hidden">
                <p class="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                    <i class="fa-solid fa-images text-blue-400"></i> Danh Sách Ảnh
                </p>
                <div id="photoGrid" class="grid grid-cols-1 sm:grid-cols-2 gap-3"></div>
            </div>
        </div>
    </main>

    <footer class="w-full text-center py-4 text-xs text-slate-600">
        Universal Downloader • 2026
    </footer>

    <script>
        async function forceDownload(url, filename, btnElement) {
            const originalHTML = btnElement.innerHTML;
            btnElement.disabled = true;
            btnElement.innerHTML = '<i class="fa-solid fa-spinner animate-spin"></i> Đang tải...';

            try {
                const response = await fetch(url);
                if (!response.ok) throw new Error('Không thể tải');
                const blob = await response.blob();
                const blobUrl = window.URL.createObjectURL(blob);
                
                const link = document.createElement('a');
                link.href = blobUrl;
                link.download = filename;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                window.URL.revokeObjectURL(blobUrl);
            } catch (err) {
                window.open(url, '_blank');
            } finally {
                btnElement.disabled = false;
                btnElement.innerHTML = originalHTML;
            }
        }

        function detectPlatform(val) {
            const iconDiv = document.getElementById('platformIcon');
            const url = val.toLowerCase();
            if (url.includes('tiktok.com')) {
                iconDiv.innerHTML = '<i class="fa-brands fa-tiktok text-white"></i>';
            } else if (url.includes('youtube.com') || url.includes('youtu.be')) {
                iconDiv.innerHTML = '<i class="fa-brands fa-youtube text-red-500"></i>';
            } else if (url.includes('facebook.com') || url.includes('fb.watch') || url.includes('fb.com')) {
                iconDiv.innerHTML = '<i class="fa-brands fa-facebook text-blue-500"></i>';
            } else if (url.includes('instagram.com')) {
                iconDiv.innerHTML = '<i class="fa-brands fa-instagram text-pink-500"></i>';
            } else {
                iconDiv.innerHTML = '<i class="fa-solid fa-link text-slate-400"></i>';
            }
        }

        async function extractLink() {
            const urlInput = document.getElementById('urlInput');
            const btn = document.getElementById('btnSubmit');
            const btnText = document.getElementById('btnText');
            const btnIcon = document.getElementById('btnIcon');
            const resultCard = document.getElementById('resultCard');
            const errorBox = document.getElementById('errorBox');
            const errorMsg = document.getElementById('errorMsg');

            const val = urlInput.value.trim();
            if (!val) return alert('Vui lòng dán liên kết!');

            btn.disabled = true;
            btnText.innerText = 'Đang Quét...';
            btnIcon.className = 'fa-solid fa-spinner animate-spin text-xs';
            resultCard.classList.add('hidden');
            errorBox.classList.add('hidden');

            try {
                const res = await fetch('/api/extract', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: val })
                });

                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Không thể bóc tách liên kết!');

                document.getElementById('mediaTitle').innerText = data.title || 'Nội dung tải về';
                document.getElementById('platformTag').innerText = data.platform || 'Media';
                document.getElementById('mediaThumb').src = data.thumbnail || '';

                const audioSection = document.getElementById('audioSection');
                const btnAudio = document.getElementById('btnAudio');
                if (data.audio_url) {
                    audioSection.classList.remove('hidden');
                    btnAudio.onclick = () => forceDownload(data.audio_url, 'audio.mp3', btnAudio);
                } else {
                    audioSection.classList.add('hidden');
                }

                const videoSection = document.getElementById('videoSection');
                const videoFormatsList = document.getElementById('videoFormatsList');
                videoFormatsList.innerHTML = '';

                if (data.video_formats && data.video_formats.length > 0) {
                    videoSection.classList.remove('hidden');
                    data.video_formats.forEach(f => {
                        const btnVid = document.createElement('button');
                        btnVid.className = 'w-full bg-slate-800/80 hover:bg-slate-700/80 border border-slate-700 p-3 rounded-xl flex items-center justify-between text-sm transition font-medium text-slate-200';
                        btnVid.innerHTML = `
                            <span class="flex items-center gap-2">
                                <i class="fa-solid fa-circle-play text-emerald-400"></i>
                                <span>MP4 - Chất lượng: <strong class="text-white">${f.quality}</strong></span>
                            </span>
                            <span class="text-xs bg-emerald-500/20 text-emerald-400 font-bold px-3 py-1.5 rounded-lg border border-emerald-500/30">Tải Video</span>
                        `;
                        btnVid.onclick = () => forceDownload(f.url, `video_${f.quality}.mp4`, btnVid);
                        videoFormatsList.appendChild(btnVid);
                    });
                } else {
                    videoSection.classList.add('hidden');
                }

                const photoSection = document.getElementById('photoSection');
                const photoGrid = document.getElementById('photoGrid');
                photoGrid.innerHTML = '';

                if (data.photos && data.photos.length > 0) {
                    photoSection.classList.remove('hidden');
                    data.photos.forEach((photoUrl, idx) => {
                        const div = document.createElement('div');
                        div.className = 'bg-slate-900 border border-slate-800 rounded-2xl p-3 flex flex-col gap-3';
                        div.innerHTML = `
                            <img src="${photoUrl}" class="w-full h-48 object-cover rounded-xl bg-black">
                            <button class="w-full bg-blue-600 hover:bg-blue-500 text-white font-semibold py-2.5 rounded-xl text-xs flex items-center justify-center gap-1.5 transition">
                                <i class="fa-solid fa-download"></i> Tải Ảnh #${idx + 1}
                            </button>
                        `;
                        const dlBtn = div.querySelector('button');
                        dlBtn.onclick = () => forceDownload(photoUrl, `photo_${idx + 1}.jpg`, dlBtn);
                        photoGrid.appendChild(div);
                    });
                } else {
                    photoSection.classList.add('hidden');
                }

                resultCard.classList.remove('hidden');
            } catch (err) {
                errorMsg.innerText = err.message;
                errorBox.classList.remove('hidden');
            } finally {
                btn.disabled = false;
                btnText.innerText = 'Xử Lý';
                btnIcon.className = 'fa-solid fa-arrow-right text-xs';
            }
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home_page():
    return HTML_CONTENT

@app.post("/api/extract")
async def extract_media(raw_request: Request):
    try:
        body_bytes = await raw_request.body()
        body_str = re.sub(r'[\x00-\x1F\x7F]', ' ', body_bytes.decode("utf-8", errors="ignore"))
        payload = json.loads(body_str)
        target_url = clean_url(payload.get("url", ""))
    except Exception:
        raise HTTPException(status_code=400, detail="Dữ liệu gửi lên không đúng chuẩn JSON")

    if not target_url:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp link cần tải")

    if "tiktok.com" in target_url:
        res = extract_tiktok_direct(target_url)
        if res: return res

    if "instagram.com" in target_url:
        res = extract_instagram_media(target_url)
        if res: return res

    if any(fb in target_url for fb in ["facebook.com", "fb.watch", "fb.com"]):
        res = extract_facebook_media(target_url)
        if res: return res

    try:
        return extract_ytdlp_engine(target_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Lỗi trích xuất: {str(e)}")
