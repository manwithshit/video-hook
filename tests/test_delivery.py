import argparse
import copy
import json
import math
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skill/scripts'))
import hook


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, rate='30', size='320x180', duration=6):
        self.video = self.root/'测试 原片.mp4'
        self.srt = self.root/'原片.srt'
        hook.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'testsrc2=size={size}:rate={rate}:duration={duration}',
                  '-f', 'lavfi', '-i', f'sine=frequency=440:sample_rate=44100:duration={duration}',
                  '-c:v', 'libx264', '-threads', '2', '-c:a', 'aac', '-shortest', self.video])
        self.srt.write_text('1\n00:00:00,000 --> 00:00:01,000\n第一句\n\n2\n00:00:02,000 --> 00:00:03,000\n中段\n\n3\n00:00:05,000 --> 00:00:06,000\n结尾\n')
        hook.prepare(argparse.Namespace(video=self.video, srt=self.srt, out=self.root/'prepared', samples=2))
        self.plan = self.root/'plan.json'
        p = hook.read(self.root/'prepared/plan.template.json')
        fps = float(hook.Fraction(str(p['fps'])))
        p.update(theme='测试主题', theme_connection='测试关联', surprise='可见变化', preserved_meaning='保留顺序',
                 segments=[[0, round(fps)/fps], [round(2*fps)/fps, round(3*fps)/fps]],
                 existing_opening={'status':'none', 'body_start':0})
        hook.write(self.plan, p)
        return p

    def preview(self, plan=None, name='preview', seconds=2):
        folder=self.root/name
        hook.render(argparse.Namespace(plan=plan or self.plan, out=folder, max_side=160, body_seconds=seconds))
        return folder

    def approve(self, preview, opening=''):
        hook.approve(argparse.Namespace(render=preview, quote='Synthetic fixture approval only', opening_quote=opening))

    def deliver(self, preview, name='delivery'):
        return hook.prepend(argparse.Namespace(render=preview, out=self.root/name))

    def pixels(self, video, t):
        return subprocess.check_output(['ffmpeg','-v','error','-ss',str(t),'-i',str(video),'-frames:v','1',
                                        '-vf','scale=32:18','-pix_fmt','rgb24','-f','rawvideo','-'])

    def audio(self, video, t):
        b=subprocess.check_output(['ffmpeg','-v','error','-ss',str(t),'-i',str(video),'-t','0.15','-vn',
                                    '-ac','1','-ar','48000','-f','f32le','-'])
        return [v[0] for v in struct.iter_unpack('<f',b)]

    def test_complete_body_pixels_audio_subtitles_and_source_size(self):
        p=self.fixture();before=hook.digest(self.video)
        preview=self.preview();self.approve(preview);result=self.deliver(preview)
        length=hook.hook_duration(p);target=result['output']
        self.assertEqual(result['qa']['width'],320)
        self.assertAlmostEqual(result['qa']['duration'],length+6,places=2)
        for t in [0,3,5.9]:
            source=self.pixels(self.video,t);actual=self.pixels(target,length+t)
            self.assertLess(sum(abs(a-b) for a,b in zip(source,actual))/len(source),4)
        # Decode the middle of the retained body, rather than treating silent AAC as valid audio.
        original=self.audio(self.video,3);actual=self.audio(target,length+3)
        rms=lambda xs:math.sqrt(sum(x*x for x in xs)/len(xs))
        self.assertGreater(rms(actual),.05)
        self.assertAlmostEqual(rms(original),rms(actual),delta=.01)
        cues=hook.parse_srt(result['srt']);body=cues[-3:]
        self.assertEqual([c['text'] for c in body],['第一句','中段','结尾'])
        self.assertAlmostEqual(body[0]['start'],length,places=3)
        self.assertAlmostEqual(body[-1]['end'],length+6,places=3)
        self.assertEqual(before,hook.digest(self.video))
        # The final command reads the source, never the 160px review proxy.
        cmd=hook.read(self.root/'delivery/command.json')
        self.assertNotIn(str(preview/'hook.mp4'),cmd)

    def test_versioned_outputs_and_sidecar_collision(self):
        self.fixture();preview=self.preview();self.approve(preview)
        occupied=self.root/'测试 原片_hook_v1.srt';occupied.write_text('keep me')
        result=self.deliver(preview)
        self.assertEqual(Path(result['output']).name,'测试 原片_hook_v2.mp4')
        old=hook.digest(result['output']);again=self.deliver(preview,'delivery2')
        self.assertEqual(Path(again['output']).name,'测试 原片_hook_v3.mp4')
        self.assertEqual(occupied.read_text(),'keep me');self.assertEqual(old,hook.digest(result['output']))
        with self.assertRaises(FileExistsError):self.deliver(preview)

    def test_approval_required_and_bound_to_all_review_artifacts(self):
        self.fixture();preview=self.preview()
        with self.assertRaises(FileNotFoundError):self.deliver(preview)
        self.approve(preview)
        for filename in ['plan.json','hook.mp4','hook.srt','preview.mp4','preview.srt','manifest.json']:
            with self.subTest(filename=filename):
                p=preview/filename;original=p.read_bytes();p.write_bytes(original+b' ')
                with self.assertRaises((ValueError,json.JSONDecodeError)):self.deliver(preview)
                self.assertFalse((self.root/'delivery').exists())
                p.write_bytes(original)
        old=self.srt.read_bytes();self.srt.write_bytes(old+b'\n')
        with self.assertRaises(ValueError):self.deliver(preview)
        self.srt.write_bytes(old)
        with self.video.open('ab') as f:f.write(b'changed')
        with self.assertRaises(ValueError):self.deliver(preview)

    def test_existing_opening_keep_or_replace(self):
        p=self.fixture();p['existing_opening']={'status':'present','body_start':2}
        self.plan.write_text(json.dumps(p));preview=self.preview()
        with self.assertRaises(ValueError):self.approve(preview)
        with self.assertRaises(ValueError):self.approve(preview,'  ')
        self.approve(preview,'Synthetic request: replace first 2 seconds')
        result=self.deliver(preview);self.assertAlmostEqual(result['body_duration'],4)
        self.assertAlmostEqual(result['qa']['duration'],hook.hook_duration(p)+4,places=2)
        self.assertEqual(hook.parse_srt(result['srt'])[-2]['text'],'中段')
        p['existing_opening']['body_start']=0;self.plan.write_text(json.dumps(p))
        kept=self.preview(name='keep');self.approve(kept,'Synthetic request: keep existing opening')
        result=self.deliver(kept,'kept');self.assertAlmostEqual(result['body_duration'],6)

    def test_unknown_opening_cannot_approve(self):
        p=self.fixture();p['existing_opening']['status']='unknown';self.plan.write_text(json.dumps(p))
        preview=self.preview()
        with self.assertRaises(ValueError):self.approve(preview)

    def test_fractional_fps_portrait_source_delivery(self):
        p=self.fixture(rate='30000/1001',size='180x320');preview=self.preview();self.approve(preview)
        result=self.deliver(preview)
        self.assertEqual((result['qa']['width'],result['qa']['height']),(180,320))
        self.assertAlmostEqual(result['qa']['fps'],30000/1001,places=5)
        self.assertEqual(result['qa']['frames'],result['qa']['expected_frames'])
        self.assertGreaterEqual(result['body_duration'],hook.media_info(self.video)[2])

    def test_preview_auto_cue_end_and_explicit_short_source(self):
        self.fixture(duration=22)
        self.srt.write_text('1\n00:00:00,000 --> 00:00:01,000\n开头\n\n2\n00:00:13,000 --> 00:00:16,633\n完整句末\n\n3\n00:00:18,000 --> 00:00:19,000\n后句\n')
        p=hook.read(self.plan);p['source']['srt_sha256']=hook.digest(self.srt);self.plan.write_text(json.dumps(p))
        preview=self.preview(seconds=None)
        m=hook.read(preview/'manifest.json')
        self.assertAlmostEqual(m['preview']['body_duration'],499/30)
        self.assertEqual(hook.parse_srt(preview/'preview.srt')[-1]['text'],'完整句末')
        self.assertEqual(hook.preview_length(p,6,30,20),6)
        for value in [0,-1,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):hook.preview_length(p,22,30,value)

    def test_failed_encode_leaves_no_published_output(self):
        self.fixture();preview=self.preview();self.approve(preview)
        real=hook.run
        def fail_encode(cmd):
            if cmd[0]=='ffmpeg' and '-filter_complex' in cmd:
                raise subprocess.CalledProcessError(1,cmd,stderr='synthetic encoder failure')
            return real(cmd)
        with patch.object(hook,'run',side_effect=fail_encode):
            with self.assertRaises(subprocess.CalledProcessError):self.deliver(preview)
        self.assertFalse(list(self.root.glob('*_hook_v*')))
        self.assertFalse(list(self.root.glob('.*_hook_v*.lock')))
        self.assertTrue(self.video.exists())

    def test_legacy_preview_requires_new_joined_review(self):
        self.fixture();preview=self.preview()
        m=hook.read(preview/'manifest.json');m.pop('schema_version');(preview/'manifest.json').write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'joined preview'):self.approve(preview)

    def test_copy_failure_leaves_no_delivery_or_hidden_files(self):
        self.fixture();preview=self.preview();self.approve(preview)
        with patch.object(hook.shutil,'copyfileobj',side_effect=OSError('synthetic disk full')):
            with self.assertRaises(OSError):self.deliver(preview)
        self.assertFalse(list(self.root.glob('*_hook_v*')))
        self.assertFalse(list(self.root.glob('.*_hook_v*')))
        self.assertTrue((self.root/'delivery/final.mp4').exists())

    def test_receipt_collision_during_publish_preserves_other_writer(self):
        self.fixture();preview=self.preview();self.approve(preview)
        link=hook.os.link
        def race(src,dst):
            if Path(dst).suffix=='.json':
                Path(dst).write_text('another writer')
            return link(src,dst)
        with patch.object(hook.os,'link',side_effect=race):
            with self.assertRaises(FileExistsError):self.deliver(preview)
        self.assertEqual((self.root/'测试 原片_hook_v1.json').read_text(),'another writer')
        self.assertFalse(list(self.root.glob('*_hook_v*.mp4')))
        self.assertFalse(list(self.root.glob('*_hook_v*.srt')))
        self.assertFalse(list(self.root.glob('.*_hook_v*')))

    def test_source_frame_rate_cannot_be_changed_by_preview(self):
        p=self.fixture();p['fps']='25';self.plan.write_text(json.dumps(p))
        preview=self.preview();self.approve(preview)
        with self.assertRaisesRegex(ValueError,'source frame rate'):self.deliver(preview)
        self.assertFalse((self.root/'delivery').exists())

if __name__=='__main__':unittest.main()
