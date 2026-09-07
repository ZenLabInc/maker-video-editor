import json
from pathlib import Path
import tempfile
import unittest

from maker_video_editor.youtube import digest, upload_private


class Response:
    def __init__(self,status=200,data=None,headers=None):
        self.status_code=status; self.data=data or {}; self.headers=headers or {}
    def json(self):
        return self.data


class Session:
    def __init__(self,responses):
        self.responses=iter(responses); self.calls=[]
    def request(self,method,url,**kwargs):
        self.calls.append((method,url,kwargs))
        result=next(self.responses)
        if isinstance(result,Exception):
            raise result
        return result


class YouTubeTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); video=self.root/'video.mp4'; video.write_bytes(b'01234567')
        self.manifest={'video':str(video),'sha256':digest(video),'bytes':8,
            'body':{'snippet':{'title':'Test'},'status':{'privacyStatus':'private'}}}
        Path(str(video)+'.subtitles.json').write_text(json.dumps({'video_sha256':digest(video)}))
        self.channel=Response(data={'items':[{'id':'channel','snippet':{'title':'Test'}}]})
        self.started=Response(headers={'Location':'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=test'})
        self.complete=Response(data={'id':'video123'})
        self.verified=Response(data={'items':[{'snippet':{'channelId':'channel'},
            'status':{'privacyStatus':'private','uploadStatus':'processed'},
            'processingDetails':{'processingStatus':'succeeded'}}]})

    def test_private_and_duplicate_prevention(self):
        session=Session([self.channel,self.started,Response(308),self.complete,self.verified])
        result=upload_private(self.manifest,'channel',False,self.root/'ledger',session)
        self.assertEqual(result['state'],'complete')
        post=next(c for c in session.calls if c[0]=='POST')
        self.assertEqual(post[2]['json']['status']['privacyStatus'],'private')
        self.assertFalse(post[2]['json']['status']['selfDeclaredMadeForKids'])
        again=Session([self.channel,self.verified])
        upload_private(self.manifest,'channel',False,self.root/'ledger',again)
        self.assertFalse(any(c[0]=='POST' for c in again.calls))

    def test_resume_from_server_range_after_network_failure(self):
        first=Session([self.channel,self.started,Response(308),OSError('transport failure with secret URL')])
        with self.assertRaisesRegex(ValueError,'interrupted'):
            upload_private(self.manifest,'channel',False,self.root/'resume',first,chunk_bytes=4)
        resume=Session([self.channel,Response(308,headers={'Range':'bytes=0-3'}),self.complete,self.verified])
        result=upload_private(self.manifest,'channel',False,self.root/'resume',resume,chunk_bytes=4)
        put=next(c for c in resume.calls if c[2].get('data'))
        self.assertEqual(put[2]['headers']['Content-Range'],'bytes 4-7/8')
        self.assertEqual(put[2]['data'],b'4567')
        self.assertEqual(result['state'],'complete')

    def test_public_wrong_channel_or_expired_session_never_uploads_new(self):
        self.manifest['body']['status']['privacyStatus']='public'
        with self.assertRaisesRegex(ValueError,'private'):
            upload_private(self.manifest,'channel',False,self.root/'bad',Session([]))
        self.manifest['body']['status']['privacyStatus']='private'
        with self.assertRaisesRegex(ValueError,'channel'):
            upload_private(self.manifest,'other',False,self.root/'bad',Session([self.channel]))
        initial=Session([self.channel,self.started,Response(404)])
        with self.assertRaisesRegex(ValueError,'no new session'):
            upload_private(self.manifest,'channel',False,self.root/'expired',initial)
        retry=Session([self.channel,Response(404)])
        with self.assertRaises(ValueError):
            upload_private(self.manifest,'channel',False,self.root/'expired',retry)
        self.assertFalse(any(c[0]=='POST' for c in retry.calls))

    def test_processing_failure_and_retry_backoff(self):
        failed=Response(data={'items':[{'snippet':{'channelId':'channel'},
            'status':{'privacyStatus':'private','uploadStatus':'failed'}}]})
        session=Session([self.channel,self.started,Response(503),Response(308),self.complete,failed])
        delays=[]
        result=upload_private(self.manifest,'channel',False,self.root/'failed',session,sleep=delays.append)
        self.assertEqual(result['state'],'processing_failed')
        self.assertEqual(len(delays),1)
