"""Local-only YouTube audio studio. Run with .venv/bin/python server.py."""
import json, os, re, shutil, subprocess, sys, tempfile, threading, time, uuid
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote

ROOT = Path(__file__).parent.resolve()
ON_VERCEL = os.environ.get('VERCEL') == '1'
DOWNLOADS = (Path(tempfile.gettempdir()) / 'dj-eddy-downloads') if ON_VERCEL else ROOT / '.downloads'
DOWNLOADS.mkdir(parents=True, exist_ok=True)
JOBS = {}
LOCK = threading.Lock()
PORT = int(os.environ.get('PORT', '8765'))

def allowed_hosts():
    hosts = {f'localhost:{PORT}', f'127.0.0.1:{PORT}'}
    if ON_VERCEL:
        hosts.add('dj-eddy-youtube-download.vercel.app')
        hosts.update(os.environ[key] for key in ('VERCEL_URL', 'VERCEL_PROJECT_PRODUCTION_URL', 'VERCEL_BRANCH_URL') if os.environ.get(key))
    return hosts

def canonical_url(value):
    p = urlparse(value.strip())
    if p.scheme not in ('https', 'http') or p.username or p.password:
        raise ValueError('Enter a valid YouTube video link.')
    host = (p.hostname or '').lower()
    if host == 'youtu.be':
        video = p.path.strip('/')
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        video = parse_qs(p.query).get('v', [''])[0] if p.path == '/watch' else (p.path.split('/')[2] if re.match(r'^/(shorts|live|embed)/', p.path) else '')
    else:
        raise ValueError('Please use a youtube.com or youtu.be video link.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
        raise ValueError('This link does not contain a valid YouTube video ID.')
    return 'https://www.youtube.com/watch?v=' + video

def convert(job_id, url, fmt):
    job = JOBS[job_id]
    folder = DOWNLOADS / job_id
    def progress(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            job.update(status='downloading', message='Downloading the best available audio…', progress=min(95, round(d.get('downloaded_bytes', 0) / total * 95)) if total else None)
        elif d['status'] == 'finished':
            job.update(status='processing', message='Preparing your audio file…', progress=96)
    try:
        import yt_dlp
        import imageio_ffmpeg
        folder.mkdir()
        opts = {'js_runtimes': {'node': {}}, 'format': 'bestaudio', 'noplaylist': True, 'outtmpl': str(folder / 'source.%(ext)s'), 'quiet': True, 'no_warnings': True, 'socket_timeout': 25, 'retries': 2, 'progress_hooks': [progress], 'max_filesize': 500 * 1024 * 1024}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get('is_live') or info.get('live_status') == 'is_live':
                raise ValueError('Live streams are not supported. Try a finished video.')
            if (info.get('duration') or 0) > 3 * 60 * 60:
                raise ValueError('Please choose a video under three hours.')
            job['title'] = info.get('title', 'Audio')
            info = ydl.process_ie_result(info, download=True)
            source = Path(ydl.prepare_filename(info))
        if not source.is_file():
            raise ValueError('The audio download did not finish. Please try again.')
        ext = source.suffix.lstrip('.')
        if fmt != 'original':
            job.update(status='processing', message='Converting to ' + fmt.upper() + '…', progress=97)
            target = folder / ('audio.' + fmt)
            codec = ['-c:a', 'libmp3lame', '-b:a', '320k'] if fmt == 'mp3' else ['-c:a', 'pcm_s24le']
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-y', '-i', str(source), '-vn', *codec, '-metadata', 'title=' + job['title'], str(target)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=600)
            source.unlink()
            source, ext = target, fmt
        title = re.sub(r'[^\w\- .()]', '', job['title'])[:150].strip() or 'audio'
        job.update(status='complete', message='Your audio is ready.', progress=100, path=str(source), filename=title + '.' + ext, size=source.stat().st_size, format=ext.upper())
    except Exception as exc:
        message = str(exc)
        if 'Sign in' in message or '403' in message or 'bot' in message:
            message = 'YouTube blocked this request. Try another public video or update yt-dlp.'
        elif isinstance(exc, subprocess.SubprocessError):
            message = 'Audio conversion failed. Try Original format or a shorter video.'
        job.update(status='error', message=re.sub(r'\x1b\[[0-9;]*m', '', message)[:350], progress=0)
        shutil.rmtree(folder, ignore_errors=True)

class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)
    def do_POST(self):
        if self.headers.get('Host') not in allowed_hosts():
            return self.send_json({'error': 'Invalid host.'}, 403)
        origin = self.headers.get('Origin')
        allowed_origins = {f'http://localhost:{PORT}', f'http://127.0.0.1:{PORT}'}
        if ON_VERCEL:
            allowed_origins.update('https://' + host for host in allowed_hosts() if host not in (f'localhost:{PORT}', f'127.0.0.1:{PORT}'))
        if origin and origin not in allowed_origins:
            return self.send_json({'error': 'Invalid origin.'}, 403)
        if self.path != '/api/convert':
            return self.send_json({'error': 'Not found.'}, 404)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length < 4096:
                raise ValueError('Invalid request size.')
            data = json.loads(self.rfile.read(length))
            url = canonical_url(data.get('url', ''))
            fmt = data.get('format', 'original')
            if fmt not in ('original', 'mp3', 'wav'):
                raise ValueError('Choose Original, MP3, or WAV.')
            with LOCK:
                if any(j['status'] not in ('complete', 'error') for j in JOBS.values()):
                    return self.send_json({'error': 'A conversion is already running. Please wait.'}, 429)
                for key, job in list(JOBS.items()):
                    if time.time() - job['created'] > 3600:
                        shutil.rmtree(DOWNLOADS / key, ignore_errors=True)
                        del JOBS[key]
                key = uuid.uuid4().hex
                JOBS[key] = {'status': 'starting', 'message': 'Finding the best audio source…', 'progress': None, 'created': time.time()}
            threading.Thread(target=convert, args=(key, url, fmt), daemon=True).start()
            self.send_json({'id': key}, 202)
        except (ValueError, TypeError, AttributeError) as exc:
            self.send_json({'error': str(exc)}, 400)
    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith('/api/jobs/'):
            job = JOBS.get(path.rsplit('/', 1)[-1])
            return self.send_json({k:v for k,v in job.items() if k != 'path'} if job else {'error': 'This download has expired.'}, 200 if job else 404)
        if path.startswith('/download/'):
            job = JOBS.get(path.rsplit('/', 1)[-1])
            if not job or job['status'] != 'complete' or not Path(job['path']).is_file():
                return self.send_json({'error': 'This download is unavailable.'}, 404)
            self.send_response(200)
            self.send_header('Content-Type', {'MP3':'audio/mpeg','WAV':'audio/wav','M4A':'audio/mp4','WEBM':'audio/webm'}.get(job['format'], 'application/octet-stream'))
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(job['filename']))
            self.send_header('Content-Length', str(job['size']))
            self.end_headers()
            with open(job['path'], 'rb') as f:
                shutil.copyfileobj(f, self.wfile)
            return
        files = {'/':'index.html', '/app.js':'app.js', '/style.css':'style.css'}
        if path not in files:
            return self.send_json({'error':'Not found.'},404)
        file = ROOT / 'public' / files[path]
        raw = file.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', {'html':'text/html; charset=utf-8','js':'text/javascript','css':'text/css'}[file.suffix[1:]])
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        self.wfile.write(raw)

# Vercel's Python runtime looks for this lowercase export.
handler = Handler

if __name__ == '__main__':
    for stale in DOWNLOADS.iterdir():
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
    print(f'DJ EDDY is running at http://localhost:{PORT}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
