import errno, importlib.util, io, json, os, sys, tempfile, unittest, uuid, wave
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class FakeYoutubeDL:
    def __init__(self,opts): self.opts=opts
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def extract_info(self,*args,**kwargs): return {'title':'Test audio','duration':1,'ext':'wav'}
    def prepare_filename(self,info): return self.opts['outtmpl'].replace('%(ext)s','wav')
    def process_ie_result(self,info,download=True):
        with wave.open(self.prepare_filename(info),'wb') as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(44100); f.writeframes(b'\0\0'*44100)
        return info

class ConversionTests(unittest.TestCase):
    def test_vercel_conversion_finishes_before_response(self):
        request = object.__new__(server.Handler)
        body = json.dumps({'url': 'https://youtu.be/aqz-KE-bpKQ', 'format': 'original'}).encode()
        request.path = '/api/convert'
        request.headers = {'Host': 'dj-eddy-youtube-download.vercel.app', 'Origin': 'https://dj-eddy-youtube-download.vercel.app', 'Content-Length': str(len(body))}
        request.rfile = io.BytesIO(body)
        events = []
        def convert(key, url, fmt):
            events.append('convert')
            server.JOBS[key].update(status='error', message='Extractor unavailable')
        def respond(data, status=200):
            events.append('respond')
            self.assertEqual(status, 502)
            self.assertEqual(data, {'error': 'Extractor unavailable'})
        request.send_json = respond
        with patch.object(server, 'ON_VERCEL', True), patch.object(server, 'JOBS', {}), patch.object(server, 'convert', convert), patch('threading.Thread') as thread:
            request.do_POST()
            thread.assert_not_called()
        self.assertEqual(events, ['convert', 'respond'])

    def test_vercel_import_with_read_only_project(self):
        spec = importlib.util.spec_from_file_location('vercel_test_server', server.__file__)
        module = importlib.util.module_from_spec(spec)
        mkdir = Path.mkdir
        def guarded_mkdir(path, *args, **kwargs):
            if path.is_relative_to(server.ROOT):
                raise OSError(errno.EROFS, 'Read-only file system', str(path))
            return mkdir(path, *args, **kwargs)
        with tempfile.TemporaryDirectory() as scratch:
            with patch.dict(os.environ, {'VERCEL': '1', 'VERCEL_URL': 'preview.vercel.app'}), patch('tempfile.gettempdir', return_value=scratch), patch.object(Path, 'mkdir', guarded_mkdir):
                spec.loader.exec_module(module)
            self.assertEqual(module.DOWNLOADS, Path(scratch) / 'dj-eddy-downloads')
            self.assertTrue(module.DOWNLOADS.is_dir())
            self.assertIs(module.handler, module.Handler)
            with patch.dict(os.environ, {'VERCEL_URL': 'preview.vercel.app'}):
                self.assertIn('preview.vercel.app', module.allowed_hosts())
                self.assertIn('dj-eddy-youtube-download.vercel.app', module.allowed_hosts())
                self.assertNotIn('evil.com', module.allowed_hosts())

    def test_storage_failure_marks_job_failed(self):
        key = uuid.uuid4().hex
        server.JOBS[key] = {'status': 'starting'}
        try:
            with patch.object(Path, 'mkdir', side_effect=OSError('No space left on device')):
                server.convert(key, 'https://youtu.be/aqz-KE-bpKQ', 'mp3')
            self.assertEqual(server.JOBS[key]['status'], 'error')
            self.assertIn('No space', server.JOBS[key]['message'])
        finally:
            server.JOBS.pop(key)

    def test_url_validation(self):
        self.assertEqual(server.canonical_url('https://youtu.be/aqz-KE-bpKQ?t=1'),'https://www.youtube.com/watch?v=aqz-KE-bpKQ')
        for value in ['https://evil.com/watch?v=aqz-KE-bpKQ','file:///etc/passwd','https://youtube.com/playlist?list=bad','https://youtu.be/bad']:
            with self.assertRaises(ValueError): server.canonical_url(value)
    def test_real_audio_encoding(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server,'DOWNLOADS',Path(folder)), patch('yt_dlp.YoutubeDL',FakeYoutubeDL):
            for fmt in ['original','mp3','wav']:
                key=uuid.uuid4().hex; server.JOBS[key]={}
                server.convert(key,'https://youtu.be/aqz-KE-bpKQ',fmt)
                job=server.JOBS.pop(key)
                self.assertEqual(job['status'],'complete',job)
                content=Path(job['path']).read_bytes()
                self.assertGreater(len(content),1000)
                if fmt=='mp3': self.assertTrue(content.startswith(b'ID3') or content[:1]==b'\xff')
                else: self.assertTrue(content.startswith(b'RIFF'))
if __name__=='__main__': unittest.main()
