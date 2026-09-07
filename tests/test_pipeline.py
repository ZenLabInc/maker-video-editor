import array
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from maker_video_editor.engine import create_plan, probe, render, run, validate
from maker_video_editor.cli import main


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        for name, color, audio in [('hands', 'red', True), ('screen', 'blue', True), ('mute', 'green', False)]:
            args = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color={color}:s=320x180:r=20:d=8']
            if audio:
                args += ['-f', 'lavfi', '-i', "aevalsrc=if(between(t\\,1\\,2)\\,0.2*sin(2*PI*440*t)\\,0):s=48000:d=8", '-c:a', 'aac']
            run(args+['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-shortest', cls.root/f'{name}.mp4'])
        cls.config = {'hands': 'hands.mp4', 'screen': 'screen.mp4', 'screen_offset': 2,
            'analysis': {'method': 'energy', 'padding': 0, 'bridge_gap': 0},
            'normal_ranges': [[6, 7]], 'hands_large_ranges': [[6, 7]],
            'output': {'width': 320, 'height': 180, 'fps': 20}}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_plan_activity_offset_manual_and_coverage(self):
        plan = create_plan(self.config, self.root)
        self.assertEqual(plan['range'], [2, 8])
        def at(t):
            return next(s for s in plan['segments'] if s['start'] <= t < s['end'])
        self.assertEqual(at(3.5)['speed'], 1)  # PC sound shifted by +2 seconds
        self.assertEqual(at(5)['speed'], 4)
        self.assertEqual(at(6.5)['layout'], 'hands')
        self.assertEqual(at(6.5)['speed'], 1)  # manual important sound
        self.assertAlmostEqual(sum(s['end']-s['start'] for s in plan['segments']), 6)

    def test_negative_offset_and_missing_audio(self):
        cfg = dict(self.config, screen='mute.mp4', screen_offset=-1)
        plan = create_plan(cfg, self.root)
        self.assertEqual(plan['range'], [0, 7])
        self.assertTrue(any('no audio' in w for w in plan['warnings']))
        cfg['screen_offset'] = 50
        with self.assertRaises(ValueError):
            create_plan(cfg, self.root)

    def test_render_layout_speed_audio_bumpers_and_cli(self):
        plan = create_plan(self.config, self.root)
        plan['range'] = [2, 7]
        plan['segments'] = [
            {'start': 2, 'end': 4, 'speed': 1, 'layout': 'screen', 'gains': {'hands': 1, 'screen': 1}},
            {'start': 4, 'end': 6, 'speed': 4, 'layout': 'screen', 'gains': {'hands': 1, 'screen': 1}},
            {'start': 6, 'end': 7, 'speed': 1, 'layout': 'hands', 'gains': {'hands': 1, 'screen': 1}}]
        output = self.root/'edited.mp4'
        result = render(plan, output)
        self.assertAlmostEqual(result['duration'], 3.5, delta=0.16)
        def pixel(t, x, y):
            data = run(['ffmpeg', '-v', 'error', '-ss', str(t), '-i', output, '-frames:v', '1',
                        '-vf', f'crop=2:2:{x}:{y}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']).stdout
            return data[:3]
        self.assertGreater(pixel(0.4, 10, 10)[2], 180)
        self.assertGreater(pixel(0.4, 240, 135)[0], 180)
        self.assertGreater(pixel(3, 10, 10)[0], 180)
        def rms(t, length):
            data = run(['ffmpeg', '-v', 'error', '-ss', str(t), '-i', output, '-t', str(length),
                        '-vn', '-ac', '1', '-f', 's16le', '-']).stdout
            values = array.array('h', data)
            return (sum(v*v for v in values)/len(values))**0.5
        self.assertGreater(rms(1.3, 0.3), 200)  # screen local 1.3 => master 3.3
        self.assertLess(rms(2.15, 0.15), 20)  # fast audio muted
        with self.assertRaises(ValueError):
            render(plan, output)
        plan['opening'] = str(self.root/'mute.mp4')
        plan['ending'] = str(self.root/'hands.mp4')
        result = render(plan, self.root/'bumpers.mp4', preview=True)
        self.assertAlmostEqual(result['duration'], 19.5, delta=0.3)
        manifest = self.root/'upload.json'
        self.assertEqual(main(['upload-manifest', str(output), str(manifest), '--title', 'Test']), 0)
        self.assertFalse(json.loads(manifest.read_text())['network_request_sent'])

    def test_session_cli_real_media_to_plan(self):
        import shutil
        directory = self.root / 'recording'
        self.assertEqual(main(['init-session', str(directory)]), 0)
        shutil.copyfile(self.root/'hands.mp4', directory/'hands'/'任意名.MP4')
        shutil.copyfile(self.root/'screen.mp4', directory/'screen'/'画面録画.mp4')
        settings = directory/'settings.json'
        config = json.loads(settings.read_text())
        config['analysis']['method'] = 'energy'
        config['screen_offset'] = 2
        settings.write_text(json.dumps(config))
        target = directory/'plan.json'
        self.assertEqual(main(['plan-session', str(directory), str(target)]), 0)
        plan = json.loads(target.read_text())
        self.assertEqual(plan['sources']['screen']['offset'], 2)
        self.assertEqual(Path(plan['sources']['hands']['path']).name, '任意名.MP4')
        self.assertEqual(main(['validate', str(target)]), 0)

    def test_validation_rejects_gaps_nan_and_bad_gains(self):
        plan = create_plan(self.config, self.root)
        for field, value in [('start', 9), ('speed', float('nan')), ('layout', 'bad')]:
            bad = copy.deepcopy(plan)
            bad['segments'][0][field] = value
            with self.assertRaises(ValueError):
                validate(bad)

    def test_silero_missing_does_not_fallback(self):
        with patch.dict('sys.modules', {'silero_vad': None, 'torch': None}):
            with self.assertRaisesRegex(ValueError, 'Silero unavailable'):
                create_plan(dict(self.config, analysis={'method': 'silero'}), self.root)


if __name__ == '__main__':
    unittest.main()
