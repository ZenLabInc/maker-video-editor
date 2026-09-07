import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from maker_video_editor.cli import main
from maker_video_editor.session import candidates, init_session, session_config


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = init_session(Path(self.temp.name) / 'shoot')

    def video(self, role, name):
        path = self.root / role / name
        path.touch()
        return path

    def test_init_does_not_merge_existing_shoot(self):
        self.assertTrue((self.root / 'settings.json').is_file())
        with self.assertRaises(FileExistsError):
            init_session(self.root)

    def test_discovery_case_hidden_subdirectories_and_links(self):
        wanted = self.video('hands', '自由な名前.MOV')
        for name in ('.hidden.mp4', '._clip.MOV', 'notes.txt'):
            self.video('hands', name)
        (self.root / 'hands' / 'another-shoot').mkdir()
        (self.root / 'hands' / 'another-shoot' / 'clip.mp4').touch()
        (self.root / 'hands' / 'link.mp4').symlink_to(wanted)
        self.assertEqual(candidates(self.root, 'hands'), [wanted])

    def test_zero_and_noninteractive_multiple_and_explicit_selection(self):
        with self.assertRaisesRegex(ValueError, 'No video'):
            session_config(self.root)
        self.video('hands', 'b.MP4'); self.video('hands', 'a.mov')
        self.video('screen', 'screen.MKV')
        with patch('sys.stdin.isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, '--hands-index'):
                session_config(self.root)
            config, _ = session_config(self.root, hands_index=2)
        self.assertEqual(Path(config['hands']).name, 'b.MP4')
        with self.assertRaisesRegex(ValueError, 'must be'):
            session_config(self.root, hands_index=0)

    def test_interactive_selection_and_cancel(self):
        self.video('hands', 'a.mov'); self.video('hands', 'b.mov')
        self.video('screen', 'screen.mov')
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value='2'):
            config, _ = session_config(self.root)
        self.assertEqual(Path(config['hands']).name, 'b.mov')
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', side_effect=EOFError):
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                session_config(self.root)

    def test_hardlinked_same_source_rejected(self):
        hands = self.video('hands', 'a.mov')
        (self.root / 'screen' / 'b.mov').hardlink_to(hands)
        with self.assertRaisesRegex(ValueError, 'same file'):
            session_config(self.root)

    def test_cli_preserves_settings_and_legacy(self):
        self.video('hands', 'camera.MOV'); self.video('screen', 'capture.mp4')
        path = self.root / 'settings.json'
        settings = json.loads(path.read_text())
        settings.update(screen_offset=3, opening='op.mp4', normal_ranges=[[10, 12]])
        path.write_text(json.dumps(settings))
        with patch('maker_video_editor.cli.create_plan', return_value={'warnings': []}) as planner:
            self.assertEqual(main(['plan-session', str(self.root), str(self.root/'plan.json')]), 0)
            config, base = planner.call_args.args
            self.assertEqual(config['screen_offset'], 3)
            self.assertEqual(config['normal_ranges'], [[10, 12]])
            self.assertEqual(config['opening'], 'op.mp4')
            self.assertEqual(base, self.root.resolve())
            self.assertEqual(main(['plan', str(path), str(self.root/'legacy.json')]), 0)
            self.assertEqual(planner.call_args.args[0], settings)

    def test_noninteractive_cli_error_does_not_write_plan(self):
        self.video('hands', 'a.mp4'); self.video('hands', 'b.mp4')
        with patch('sys.stdin.isatty', return_value=False), contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(['plan-session', str(self.root), str(self.root/'plan.json')]), 2)
        self.assertIn('--hands-index', error.getvalue())
        self.assertFalse((self.root/'plan.json').exists())
