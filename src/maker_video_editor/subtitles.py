"""Deterministic source -> master -> edited subtitle timing; models never set time."""
import html
import math
from pathlib import Path
import textwrap

from .engine import number, probe, validate
from .transcription import atomic_json


def output_time(master, segments):
    elapsed=0.0
    for segment in segments:
        if master >= segment['end']:
            elapsed += (segment['end']-segment['start'])/segment['speed']
        elif master > segment['start']:
            return elapsed+(master-segment['start'])/segment['speed']
        else:
            return elapsed
    return elapsed


def mapped_cues(english, plan, opening_seconds=0):
    cues=[]
    low,high=plan['range']
    for row in english['segments']:
        role=row['source']
        if role not in ('hands','screen'):
            raise ValueError('Unknown subtitle source')
        if Path(english['sources'][role]['path']).resolve()!=Path(plan['sources'][role]['path']).resolve():
            raise ValueError('Subtitle source does not match plan source')
        start=number(row['source_start'],'subtitle start')+plan['sources'][role]['offset']
        end=number(row['source_end'],'subtitle end')+plan['sources'][role]['offset']
        if end<start:
            raise ValueError('Invalid subtitle range')
        start,end=max(start,low),min(end,high)
        text=' '.join(row['english'].split())
        if end<=start or not text:
            continue
        a=output_time(start,plan['segments'])+opening_seconds
        b=output_time(end,plan['segments'])+opening_seconds
        # Split long English into <=2 lines, allocate display time proportionally.
        # This is readability layout, NOT inferred word-level alignment.
        lines=textwrap.wrap(text,width=42,break_long_words=True,break_on_hyphens=False)
        parts=['\n'.join(lines[i:i+2]) for i in range(0,len(lines),2)]
        weights=[len(x) for x in parts]; total=sum(weights); cursor=a
        for part,weight in zip(parts,weights):
            finish=cursor+(b-a)*weight/total
            cues.append({'id':row['id'],'source':role,'start':cursor,'end':finish,'text':part})
            cursor=finish
    return cues


def simultaneous(cues):
    # Partition time and combine simultaneous sources into one cue so players do not hide one.
    boundaries=sorted({round(c[k]*1000) for c in cues for k in ('start','end')})
    result=[]
    for a,b in zip(boundaries,boundaries[1:]):
        active=[c for c in cues if round(c['start']*1000)<=a and round(c['end']*1000)>=b]
        if not active or b<=a:
            continue
        texts=[]
        for cue in sorted(active,key=lambda c:(c['source'],c['id'])):
            prefix='[Hands] ' if cue['source']=='hands' else '[PC] '
            texts.append(prefix+cue['text'])
        text='\n'.join(texts)
        if result and result[-1]['end_ms']==a and result[-1]['text']==text:
            result[-1]['end_ms']=b
        else:
            result.append({'start_ms':a,'end_ms':b,'text':text})
    return result


def stamp(milliseconds, vtt=False):
    seconds,ms=divmod(milliseconds,1000)
    minutes,seconds=divmod(seconds,60)
    hours,minutes=divmod(minutes,60)
    return f'{hours:02}:{minutes:02}:{seconds:02}{"." if vtt else ","}{ms:03}'


def write_subtitles(english,plan,output):
    validate(plan)
    root=Path(output).resolve()
    if root.exists():
        raise ValueError('Subtitle output exists; choose a new directory.')
    opening=probe(plan['opening'])['duration'] if plan.get('opening') else 0
    cues=simultaneous(mapped_cues(english,plan,opening))
    root.mkdir(parents=True)
    for vtt,name in [(False,'english.srt'),(True,'english.vtt')]:
        blocks=['WEBVTT\n'] if vtt else []
        for i,cue in enumerate(cues,1):
            text=html.escape(cue['text'],quote=False)
            blocks.append(f'{i}\n{stamp(cue["start_ms"],vtt)} --> {stamp(cue["end_ms"],vtt)}\n{text}\n')
        (root/name).write_text('\n'.join(blocks),encoding='utf-8')
    atomic_json(root/'timing-review.json',{'opening_seconds':opening,'cues':cues,
                'warnings':['Captions spanning speed changes retain the full translation over the mapped interval.',
                            'Clipped captions retain the full sentence; review boundary meaning.',
                            'Fast or simultaneous captions may exceed reading speed; inspect preview.',
                            'Hands/PC labels identify sources, not speakers.']})
    return root/'english.srt'


def burn_subtitles(video, subtitles, output):
    """Reencode with burned English text, plus a hash proof for the private uploader."""
    import os
    import shutil
    import tempfile
    from .engine import run
    from .youtube import digest
    video=Path(video).resolve(); subtitles=Path(subtitles).resolve(); output=Path(output).resolve()
    if output.exists() or Path(str(output)+'.subtitles.json').exists():
        raise ValueError('Burned video/proof already exists; choose a new output.')
    if not subtitles.read_text().strip():
        raise ValueError('Subtitle file is empty')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.burn-',dir=output.parent) as temp:
        root=Path(temp)
        shutil.copyfile(subtitles,root/'captions.srt')
        # Run in the scratch directory so arbitrary user paths need no filter escaping.
        import subprocess
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(video),'-vf','subtitles=captions.srt',
            '-c:v','libx264','-crf','20','-preset','fast','-c:a','copy','-movflags','+faststart','burned.mp4'],
            cwd=root,check=True,capture_output=True)
        os.link(root/'burned.mp4',output)
    atomic_json(Path(str(output)+'.subtitles.json'),{'video_sha256':digest(output),
                'source_video_sha256':digest(video),'subtitle_sha256':digest(subtitles),'method':'libass-burn-in'})
    return output
