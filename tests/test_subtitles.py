import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from maker_video_editor.translation import check_translations, translate
from maker_video_editor.subtitles import mapped_cues, simultaneous, write_subtitles


class SubtitleTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.sources={role:{'path':str(self.root/f'{role}.mp4'),'offset':offset}
                      for role,offset in [('hands',0),('screen',2)]}
        self.plan={'sources':self.sources,'range':[2,10], 'opening':'op.mp4', 'segments':[
            {'start':2,'end':4,'speed':1},{'start':4,'end':8,'speed':4},{'start':8,'end':10,'speed':1}]}
        self.row={'id':'h1','source':'hands','source_start':3,'source_end':9,'text':'日本語','english':'Hello world.'}
        self.transcript={'sources':self.sources,'segments':[self.row]}

    def test_id_missing_duplicate_empty_and_unexpected_rejected(self):
        for values in [[],[{'id':'bad','english':'x'}], [{'id':'h1','english':''}],
                       [{'id':'h1','english':'a'},{'id':'h1','english':'b'}]]:
            with self.assertRaises(ValueError):
                check_translations({'translations':values},['h1'])

    def test_translation_failure_resume_without_repeating_success(self):
        transcript=copy.deepcopy(self.transcript)
        transcript['segments']=[{**self.row,'id':f'h{i}'} for i in range(21)]
        def good(payload):
            return {'translations':[{'id':r['id'],'english':'English.'} for r in payload['requested']]}
        backend=Mock(side_effect=lambda payload: good(payload) if backend.call_count==1 else {'translations':[]})
        with self.assertRaises(ValueError):
            translate(transcript,self.root/'cache',backend=backend)
        self.assertTrue((self.root/'cache'/'batch-000000.json').exists())
        self.assertFalse((self.root/'cache'/'english.json').exists())
        finish=Mock(side_effect=good)
        result=translate(transcript,self.root/'cache',resume=True,backend=finish)
        self.assertEqual(finish.call_count,1)
        self.assertEqual(len(json.loads(result.read_text())['segments']),21)
        translate(transcript,self.root/'cache',resume=True,backend=finish)
        self.assertEqual(finish.call_count,1)

    def test_speed_boundary_clipping_offset_and_opening(self):
        cues=mapped_cues(self.transcript,self.plan,opening_seconds=5)
        self.assertEqual(cues[0]['start'],6)
        self.assertEqual(cues[0]['end'],9)
        pc={**self.row,'id':'pc','source':'screen','source_start':-1,'source_end':20}
        cues=mapped_cues({**self.transcript,'segments':[pc]},self.plan,5)
        self.assertEqual(cues[0]['start'],5)
        self.assertEqual(cues[0]['end'],10)

    def test_simultaneous_and_long_empty_captions(self):
        long={**self.row,'english':'Long caption with technical terms. '*10}
        pc={**self.row,'id':'pc','source':'screen','source_start':1,'source_end':7}
        empty={**self.row,'id':'empty','english':' '}
        cues=mapped_cues({**self.transcript,'segments':[long,pc,empty]},self.plan)
        self.assertTrue(all(len(c['text'].splitlines())<=2 for c in cues))
        combined=simultaneous(cues)
        self.assertTrue(any('[Hands]' in c['text'] and '[PC]' in c['text'] for c in combined))
        self.assertTrue(all(c['end_ms']>c['start_ms'] for c in combined))

    def test_srt_vtt_and_opening_probe(self):
        with patch('maker_video_editor.subtitles.validate'), patch('maker_video_editor.subtitles.probe',return_value={'duration':5}):
            result=write_subtitles(self.transcript,self.plan,self.root/'subs')
        self.assertIn('00:00:06,000 --> 00:00:09,000',result.read_text())
        self.assertTrue((result.parent/'english.vtt').read_text().startswith('WEBVTT\n'))
        self.assertIn('00:00:06.000', (result.parent/'english.vtt').read_text())

    def test_codex_failure_is_not_cached(self):
        with self.assertRaises(RuntimeError):
            translate(self.transcript,self.root/'failed',backend=Mock(side_effect=RuntimeError('failed')))
        self.assertFalse((self.root/'failed'/'batch-000000.json').exists())
