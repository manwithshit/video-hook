import argparse
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skill/scripts'))
import hook


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_chinese_multiline_srt_and_mapping(self):
        srt = self.root / '中文.srt'
        srt.write_text('\ufeff1\r\n00:00:01,000 --> 00:00:02,500\r\n原状态\r\n补充\r\n\r\n2\r\n00:00:04,000 --> 00:00:05,000\r\n变化后的结果\r\n', encoding='utf-8')
        cues = hook.parse_srt(srt)
        mapped = hook.mapped_cues(cues, [[1.5, 3], [4, 5.5]])
        self.assertEqual(mapped[0]['start'], 0)
        self.assertEqual(mapped[0]['end'], 1)
        self.assertEqual(mapped[1]['start'], 1.5)
        self.assertEqual(mapped[1]['end'], 2.5)
        self.assertEqual(mapped[0]['text'], '原状态\n补充')
        windows = hook.build_transcript_windows({'segments': cues}, 6, 2, .5)
        self.assertIn('变化后的结果', windows[-1]['text'])

    def test_reject_invalid_srt(self):
        srt = self.root / 'bad.srt'
        srt.write_text('1\n00:00:02,000 --> 00:00:01,000\n倒序\n')
        with self.assertRaises(ValueError):
            hook.parse_srt(srt)

    def test_pipeline_and_approval_binding(self):
        video, srt = self.root / '源 视频.mp4', self.root / '字幕.srt'
        hook.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=6',
                  '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=6', '-c:v', 'libx264', '-c:a', 'aac', '-shortest', video])
        srt.write_text('1\n00:00:00,500 --> 00:00:02,000\n原来的状态\n\n2\n00:00:03,000 --> 00:00:04,500\n操作之后的结果\n')
        before = hook.digest(video)
        work = self.root / 'work'
        hook.prepare(argparse.Namespace(video=str(video), srt=str(srt), out=str(work), samples=2))
        p = hook.read(work / 'plan.template.json')
        p.update(theme='状态变化', theme_connection='操作前后状态', surprise='改变结果', preserved_meaning='仅删停顿', segments=[[.5,2],[3,4.5]])
        plan = work / 'plan.json'
        hook.write(plan, p)
        preview = self.root / 'preview'
        hook.render(argparse.Namespace(plan=str(plan), out=str(preview), max_side=160))
        self.assertEqual(hook.read(preview/'manifest.json')['hook_duration'], 3.6)
        with self.assertRaises(ValueError):
            hook.approve(argparse.Namespace(render=str(preview), quote='测试确认', opening_quote=''))
        with self.assertRaises(FileNotFoundError):
            hook.prepend(argparse.Namespace(render=str(preview), out=str(self.root/'denied')))
        p['existing_opening'] = {'status': 'none', 'body_start': 0}
        plan.write_text(json.dumps(p))
        preview2 = self.root / 'preview2'
        hook.render(argparse.Namespace(plan=str(plan), out=str(preview2), max_side=160))
        hook.approve(argparse.Namespace(render=str(preview2), quote='Synthetic test fixture approval, not user media', opening_quote=''))
        final = hook.prepend(argparse.Namespace(render=str(preview2), out=str(self.root/'final')))
        self.assertAlmostEqual(final['qa']['duration'], 9.6, places=1)
        self.assertEqual(final['qa']['width'], 320)
        self.assertEqual(hook.read(preview2/'manifest.json')['width'], 160)
        self.assertEqual(Path(final['output']).parent, video.parent.resolve())
        self.assertEqual(Path(final['output']).name, '源 视频_hook_v1.mp4')
        self.assertTrue(Path(final['srt']).exists())
        self.assertTrue(Path(final['output']).with_suffix('.json').exists())
        self.assertTrue((preview2/'preview.mp4').exists())
        self.assertEqual(final['join']['black_pixel_max'], 0)
        self.assertLess(final['join']['separator_audio_rms'], .006)
        self.assertEqual(hook.digest(video), before)
        final_cues = hook.parse_srt(self.root/'final/final.srt')
        self.assertAlmostEqual(final_cues[2]['start'], 4.1)
        # Ensure stale approval cannot authorize modified media.
        with (preview2/'hook.mp4').open('ab') as f:
            f.write(b'changed')
        with self.assertRaises(ValueError):
            hook.prepend(argparse.Namespace(render=str(preview2), out=str(self.root/'tampered')))
        # Plan failures are checked before creating any output.
        for change in ({'segments': [[3,4],[1,2]]}, {'segments': [[0,7]]}, {'segments': [[0,float('nan')]]}, {'theme_connection': ''}, {'segments': [[.501,2]]}):
            invalid = copy.deepcopy(p)
            invalid.update(change)
            plan.write_text(json.dumps(invalid))
            with self.assertRaises(ValueError):
                hook.validate_plan(plan)
        p['source']['srt_sha256'] = '0'*64
        plan.write_text(json.dumps(p))
        with self.assertRaises(ValueError):
            hook.validate_plan(plan)


if __name__ == '__main__':
    unittest.main()
