import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from maker_video_editor.engine import run
from maker_video_editor.transcription import check_model, extract_audio, timed_item, transcribe_sources


class TranscriptionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.model = cls.root/'model'
        cls.model.mkdir()
        (cls.model/'config.json').write_text(json.dumps({'n_mels':128, 'n_audio_layer':32,
            'n_text_layer':32, 'n_audio_state':1280, 'n_text_state':1280}))
        (cls.model/'weights.npz').touch()  # Test fixture only; never loaded as a real model.
        for role, audio in [('hands', 'sine=frequency=440:sample_rate=48000:duration=12'),
                            ('screen', 'anullsrc=r=48000:cl=stereo'), ('missing', None)]:
            args = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=red:s=64x64:r=10:d=12']
            if audio:
                args += ['-f', 'lavfi', '-i', audio, '-c:a', 'aac']
            run(args+['-t','12', '-c:v','libx264', cls.root/f'{role}.mp4'])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def sources(self, screen='screen'):
        return {'hands': {'path':str(self.root/'hands.mp4'), 'offset':0},
                'screen': {'path':str(self.root/f'{screen}.mp4'), 'offset':-2}}

    def backend(self):
        return Mock(return_value={'segments':[{'start':0.1, 'end':0.8, 'text':'はんだ付けです。',
            'words':[{'start':0.1, 'end':0.5, 'word':'はんだ付け'}]}]})

    def test_extract_16khz_and_source_master_timestamps(self):
        samples = extract_audio(self.root/'hands.mp4', 1, 0.5)
        self.assertAlmostEqual(len(samples)/16000, 0.5, delta=0.02)
        self.assertGreater(max(samples), 0.01)
        item = timed_item({'start':1, 'end':2, 'text':'日本語'}, 'screen', 300, -3, 10, 'text')
        self.assertEqual(item['source_start'],301)
        self.assertEqual(item['master_start'],298)
        self.assertEqual(item['source'], 'screen')

    def test_checkpoints_silence_resume_and_settings_identity(self):
        output = self.root/'resume'
        backend = self.backend()
        result = transcribe_sources(self.sources(), output, self.model, {'chunk_seconds':10}, backend=backend)
        data = json.loads(result.read_text())
        self.assertEqual(backend.call_count,2)
        self.assertEqual(data['status']['screen'],'no_text')
        self.assertEqual(data['segments'][1]['source_start'],10.1)
        self.assertEqual(data['segments'][0]['words'][0]['text'],'はんだ付け')
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            transcribe_sources(self.sources(), output, self.model, backend=backend)
        transcribe_sources(self.sources(), output, self.model, {'chunk_seconds':10}, resume=True, backend=backend)
        self.assertEqual(backend.call_count,2)
        with self.assertRaisesRegex(ValueError, 'identity differs'):
            transcribe_sources(self.sources(), output, self.model, {'chunk_seconds':20}, resume=True, backend=backend)

    def test_interrupted_resume_and_missing_track(self):
        output = self.root/'interrupted'
        good = self.backend().return_value
        broken = Mock(side_effect=[good, RuntimeError('simulated crash')])
        with self.assertRaises(RuntimeError):
            transcribe_sources(self.sources('missing'), output, self.model, {'chunk_seconds':10}, backend=broken)
        self.assertTrue((output/'hands-000000.json').exists())
        self.assertFalse((output/'.lock').exists())
        backend=self.backend()
        result=transcribe_sources(self.sources('missing'), output, self.model, {'chunk_seconds':10}, resume=True, backend=backend)
        self.assertEqual(backend.call_count,1)
        self.assertEqual(json.loads(result.read_text())['status']['screen'],'no_audio')

    def test_reject_wrong_model_and_invalid_times(self):
        with self.assertRaisesRegex(ValueError, 'missing'):
            check_model(self.root/'absent')
        with self.assertRaisesRegex(ValueError, 'timestamps'):
            timed_item({'start':2, 'end':1, 'text':'bad'},'hands',0,0,10,'text')
        wrong=self.root/'tiny'; wrong.mkdir()
        (wrong/'config.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'large-v3'):
            check_model(wrong)
