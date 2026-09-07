"""Explicit private-only YouTube uploads using official OAuth and resumable HTTP."""
import hashlib
import json
import os
from pathlib import Path
import random
import re
import tempfile
import time
from urllib.parse import urlparse

SCOPES=['https://www.googleapis.com/auth/youtube.upload','https://www.googleapis.com/auth/youtube.readonly']
SERVICE='maker-video-editor.youtube'


def digest(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file,'sha256').hexdigest()


def save_state(path,value):
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as file:
        temp=Path(file.name)
        os.chmod(temp,0o600)
        json.dump(value,file,ensure_ascii=False,indent=2)
        file.flush(); os.fsync(file.fileno())
    os.replace(temp,path)


def keychain():
    try:
        import keyring
        from keyring.backends.macOS import Keyring
    except ImportError as exc:
        raise ValueError('Install .[youtube] on macOS for OAuth and Keychain storage.') from exc
    # Never fall back silently to a plaintext credential backend.
    keyring.set_keyring(Keyring())
    return keyring


def authorize(client_file, account='default'):
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise ValueError('Install .[youtube] first.') from exc
    data=json.loads(Path(client_file).read_text())
    if 'installed' not in data:
        raise ValueError('A Desktop app OAuth client JSON is required.')
    flow=InstalledAppFlow.from_client_secrets_file(client_file,SCOPES,autogenerate_code_verifier=True)
    credentials=flow.run_local_server(host='127.0.0.1',port=0,open_browser=False,
        authorization_prompt_message='Open this Google authorization URL in the approved Chrome profile:\n{url}',
        success_message='Authorization completed. You may close this tab.',timeout_seconds=600)
    keychain().set_password(SERVICE,account,credentials.to_json())
    return 'OAuth credentials saved in macOS Keychain.'


def authorized_session(account='default'):
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import AuthorizedSession
    except ImportError as exc:
        raise ValueError('Install .[youtube] first.') from exc
    saved=keychain().get_password(SERVICE,account)
    if not saved:
        raise ValueError('YouTube OAuth missing. Run youtube-auth with a Desktop OAuth client JSON.')
    credentials=Credentials.from_authorized_user_info(json.loads(saved),SCOPES)
    return AuthorizedSession(credentials)


def safe_request(session,method,url,**kwargs):
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.netloc!='www.googleapis.com':
        raise ValueError('Refusing non-Google API upload URL')
    try:
        return session.request(method,url,timeout=60,allow_redirects=False,**kwargs)
    except Exception as exc:
        # Do not put an upload session URL/token from a transport exception into the log.
        raise ValueError('YouTube network request interrupted; rerun the same command to resume.') from None


def get_channels(session):
    response=safe_request(session,'GET','https://www.googleapis.com/youtube/v3/channels',
                          params={'part':'id,snippet','mine':'true'})
    if response.status_code!=200:
        raise ValueError(f'Channel lookup failed (HTTP {response.status_code}).')
    return [{'id':item['id'],'title':item['snippet']['title']} for item in response.json().get('items',[])]


def verify_video(session,video_id,channel_id):
    response=safe_request(session,'GET','https://www.googleapis.com/youtube/v3/videos',
                          params={'part':'status,processingDetails,snippet','id':video_id})
    if response.status_code!=200:
        raise ValueError(f'Video verification failed (HTTP {response.status_code}).')
    items=response.json().get('items',[])
    if len(items)!=1:
        return {'state':'processing','video_id':video_id,'verified_private':False}
    video=items[0]
    if video['snippet']['channelId']!=channel_id or video['status']['privacyStatus']!='private':
        raise ValueError('Video channel/privacy verification failed; no further mutation performed.')
    upload=video['status'].get('uploadStatus')
    processing=video.get('processingDetails',{}).get('processingStatus')
    if upload in ('failed','rejected','deleted') or processing in ('failed','terminated'):
        return {'state':'processing_failed','video_id':video_id,'verified_private':True}
    return {'state':'complete' if upload=='processed' or processing=='succeeded' else 'processing',
            'video_id':video_id,'verified_private':True}


def acknowledged(response,total):
    value=response.headers.get('Range')
    if not value:
        return 0
    match=re.fullmatch(r'bytes=0-(\d+)',value)
    if not match or int(match[1])+1>total:
        raise ValueError('Invalid server upload range')
    return int(match[1])+1


def upload_private(manifest,channel_id,made_for_kids,ledger,session,chunk_bytes=8*1024*1024,sleep=time.sleep):
    video=Path(manifest['video']).resolve()
    if digest(video)!=manifest['sha256'] or video.stat().st_size!=manifest['bytes']:
        raise ValueError('Video differs from prepared manifest.')
    if made_for_kids not in (True,False):
        raise ValueError('Explicit made-for-kids decision required.')
    body=json.loads(json.dumps(manifest['body']))
    if body.get('status',{}).get('privacyStatus')!='private' or 'publishAt' in body.get('status',{}):
        raise ValueError('Only private uploads without publication scheduling are supported.')
    body['status']={'privacyStatus':'private','selfDeclaredMadeForKids':made_for_kids}
    if not body.get('snippet',{}).get('title','').strip():
        raise ValueError('Video title required')
    proof=Path(str(video)+'.subtitles.json')
    if not proof.is_file() or json.loads(proof.read_text()).get('video_sha256')!=manifest['sha256']:
        raise ValueError('Burned-subtitle proof missing or mismatched. Run burn-subtitles first.')
    if channel_id not in {item['id'] for item in get_channels(session)}:
        raise ValueError('Authorized channel does not match requested channel.')
    root=Path(ledger).resolve(); root.mkdir(parents=True,exist_ok=True)
    os.chmod(root,0o700)
    identity=hashlib.sha256((channel_id+':'+manifest['sha256']).encode()).hexdigest()
    path=root/f'{identity}.json'
    lock=root/'.lock'
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as exc:
        raise ValueError('Upload ledger locked. Verify no active run before removing a stale lock.') from exc
    os.close(fd)
    try:
        state=json.loads(path.read_text()) if path.exists() else {'state':'prepared','channel_id':channel_id,
            'sha256':manifest['sha256'],'body':body,'bytes':manifest['bytes']}
        if state['body']!=body:
            raise ValueError('Upload metadata changed; refusing duplicate/replacement upload.')
        if state.get('video_id'):
            state.update(verify_video(session,state['video_id'],channel_id)); save_state(path,state)
            return {k:state[k] for k in ('state','video_id','verified_private')}
        if state['state']=='prepared':
            state['state']='initializing'; save_state(path,state)
            response=safe_request(session,'POST','https://www.googleapis.com/upload/youtube/v3/videos',
                params={'uploadType':'resumable','part':'snippet,status'},json=body,
                headers={'X-Upload-Content-Length':str(state['bytes']),'X-Upload-Content-Type':'video/mp4'})
            if response.status_code not in (200,201) or not response.headers.get('Location'):
                raise ValueError(f'Upload initialization failed (HTTP {response.status_code}); inspect state before retry.')
            state.update(state='uploading',session_url=response.headers['Location']); save_state(path,state)
        if not state.get('session_url'):
            raise ValueError('Upload initialization outcome unknown; refusing a new session. Review ledger before retry.')
        total=state['bytes']; failures=0
        while True:
            response=safe_request(session,'PUT',state['session_url'],data=b'',
                                  headers={'Content-Length':'0','Content-Range':f'bytes */{total}'})
            if response.status_code in (200,201):
                break
            if response.status_code in (429,500,502,503,504):
                failures+=1
                if failures>5:
                    raise ValueError('Upload retry limit reached; rerun later to resume.')
                sleep(min(2**failures+random.random(),32)); continue
            if response.status_code!=308:
                raise ValueError(f'Upload status failed (HTTP {response.status_code}); no new session will be created.')
            offset=acknowledged(response,total)
            if offset>=total:
                raise ValueError('All bytes received but completion is unconfirmed; rerun status later.')
            with video.open('rb') as file:
                file.seek(offset); data=file.read(chunk_bytes)
            response=safe_request(session,'PUT',state['session_url'],data=data,
                headers={'Content-Type':'video/mp4','Content-Length':str(len(data)),
                         'Content-Range':f'bytes {offset}-{offset+len(data)-1}/{total}'})
            if response.status_code in (200,201):
                break
            if response.status_code==308:
                position=acknowledged(response,total)
                if position<=offset:
                    raise ValueError('Upload made no progress; rerun later to query server state.')
                state['acknowledged']=position; save_state(path,state); failures=0
            elif response.status_code in (429,500,502,503,504):
                failures+=1
                if failures>5:
                    raise ValueError('Upload retry limit reached; rerun later to resume.')
                sleep(min(2**failures+random.random(),32))
            else:
                raise ValueError(f'Upload failed (HTTP {response.status_code}); resume state retained.')
        video_id=response.json().get('id')
        if not video_id:
            raise ValueError('Upload completion response lacks video ID; rerun to query session.')
        state.update(state='uploaded',video_id=video_id); save_state(path,state)
        state.update(verify_video(session,video_id,channel_id)); save_state(path,state)
        return {k:state[k] for k in ('state','video_id','verified_private')}
    finally:
        lock.unlink(missing_ok=True)
