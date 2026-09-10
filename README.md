# DJ EDDY
A personal, local YouTube-to-audio site. Open http://localhost:8765 while the server runs.

Double-click `start.command` on macOS, or run:

```sh
.runtime/bin/python server.py
```

On a fresh machine, use Python 3.10+ (3.13 recommended):

```sh
python3 -m venv .runtime
.runtime/bin/python -m pip install -r requirements.txt
.runtime/bin/python server.py
```

Node.js is recommended for current YouTube JavaScript challenges. FFmpeg is included through imageio-ffmpeg. No API keys required.

- **Original** downloads the best available audio-only stream without re-encoding, generally WebM/Opus or M4A. This preserves source quality.
- **MP3** converts that source to 320 kbps for compatibility.
- **WAV** converts to 24-bit PCM for editing. Neither conversion restores details absent from YouTube's compressed source.

The server binds only to 127.0.0.1. One job runs at a time. Videos are limited to three hours and downloads to 500 MB. Files stay in `.downloads`; old jobs are removed when another conversion starts after an hour. Restarting clears previous session files. This is a local personal tool, not a public multi-user service.

YouTube may restrict particular videos or block automated downloads. Errors appear in the interface. To update the extractor:

```sh
.venv/bin/uv pip install --python .runtime/bin/python --upgrade 'yt-dlp[default]'
```

Extractor documentation: https://github.com/yt-dlp/yt-dlp

Only download content you own or have permission to use.
