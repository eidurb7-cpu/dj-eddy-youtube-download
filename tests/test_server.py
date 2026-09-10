import sys, tempfile, unittest, uuid, wave
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
