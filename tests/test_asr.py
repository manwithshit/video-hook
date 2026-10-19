import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skill/scripts'))
import hook
import local_asr


class ASRTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.video = self.root / '测试 原片.mp4'

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self):
        hook.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                  'testsrc2=size=320x180:rate=30:duration=4',
                  '-itsoffset', '1', '-f', 'lavfi', '-i',
                  'sine=frequency=440:sample_rate=48000:duration=3',
                  '-c:v', 'libx264', '-threads', '2', '-c:a', 'aac', self.video])

    def args(self, **kw):
        values = dict(video=self.video, srt=None, out=self.root/'work', samples=2,
                      asr_model=None, asr_language='auto')
        values.update(kw)
        return argparse.Namespace(**values)

    def fake_backend(self, content='1\n00:00:01,000 --> 00:00:02,000\n测试结果\n', status=0):
        # A subprocess fixture tests invocation/paths/logging; not an ASR quality test.
        cli = self.root/'fake whisper cli'
        cli.write_text('#!' + sys.executable + '\nimport sys,pathlib\n'
                       'assert "-osrt" in sys.argv and "-oj" in sys.argv\n'
                       'p=pathlib.Path(sys.argv[sys.argv.index("-of")+1])\n'
                       f'p.with_suffix(".srt").write_text({content!r})\n'
                       f'print("fixture status");sys.exit({status})\n')
        cli.chmod(0o755)
        model = self.root/'test model.bin';model.write_bytes(b'fixture')
        return str(cli), model

    def test_discovery_priority_uniqueness_and_explicit_override(self):
        a = self.root/'asr';b = self.root/'edit';a.mkdir();b.mkdir()
        one=a/'测试 原片.srt';one.write_text('one')
        self.assertEqual(local_asr.discover_srt(self.video), (one,'sidecar'))
        two=b/one.name;two.write_text('two')
        with self.assertRaisesRegex(ValueError,'Multiple'):local_asr.discover_srt(self.video)
        direct=self.video.with_suffix('.srt');direct.write_text('direct')
        self.assertEqual(local_asr.discover_srt(self.video), (direct,'sidecar'))
        self.assertEqual(local_asr.discover_srt(self.video,two),(two,'explicit'))
        # Nested arbitrary timelines and different stems are deliberately ignored.
        other=self.root/'unknown'/'deep';other.mkdir(parents=True)
        (other/one.name).write_text('not the edited timeline')
        direct.unlink();one.unlink();two.unlink()
        self.assertEqual(local_asr.discover_srt(self.video),(None,'local_asr'))

    def test_explicit_srt_preserves_source_and_does_not_call_asr(self):
        self.fixture()
        srt=self.root/'manual.srt';srt.write_text('1\n00:00:00,500 --> 00:00:02,000\n原字幕\n')
        before=hook.digest(srt)
        with patch.object(local_asr,'resolve_backend',side_effect=AssertionError('ASR should not run')):
            hook.prepare(self.args(srt=srt))
        source=hook.read(self.root/'work/source.json')
        self.assertEqual(set(source),{'video','srt','video_sha256','srt_sha256'})
        self.assertEqual(source['srt_sha256'],before)
        self.assertEqual(hook.read(self.root/'work/transcript.json'),hook.parse_srt(srt))
        self.assertFalse((self.root/'work/asr').exists())
        self.assertEqual(hook.digest(srt),before)

    def test_invalid_sidecar_is_not_hidden_by_asr(self):
        self.fixture();srt=self.video.with_suffix('.srt')
        with patch.object(local_asr,'resolve_backend',side_effect=AssertionError('ASR should not run')):
            srt.write_text('invalid')
            with self.assertRaises(ValueError):hook.prepare(self.args())
            srt.write_text('1\n00:00:00,000 --> 00:00:10,000\nwrong timeline\n')
            with self.assertRaisesRegex(ValueError,'beyond'):hook.prepare(self.args())
            with self.assertRaises(FileNotFoundError):hook.prepare(self.args(srt=self.root/'absent.srt'))
        self.assertFalse((self.root/'work').exists())

    def test_missing_backend_or_model_does_not_download(self):
        with patch.object(local_asr.shutil,'which',return_value=None):
            with self.assertRaisesRegex(ValueError,'whisper-cli is missing'):local_asr.resolve_backend()
            result=local_asr.doctor()
            self.assertFalse(result['available'])
            self.assertIn('brew install whisper.cpp',result['reason'])
            self.assertIn('ggml-small.bin',result['reason'])
            self.assertIn('asr-setup.md',result['reason'])
        with patch.object(local_asr.shutil,'which',return_value=sys.executable), \
                patch.object(local_asr.Path,'home',return_value=self.root), \
                patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,'No local GGML'):local_asr.resolve_backend()
            with self.assertRaisesRegex(ValueError,'missing or empty'):local_asr.resolve_backend(self.root/'absent.bin')
            cached=self.root/'.cache/video-hook/models';cached.mkdir(parents=True)
            (cached/'ggml-base.bin').write_bytes(b'local')
            self.assertEqual(local_asr.resolve_backend()[1],cached/'ggml-base.bin')
            with patch.dict(os.environ,{'VIDEO_HOOK_ASR_MODEL':str(self.root/'absent.bin')}):
                with self.assertRaisesRegex(ValueError,'missing or empty'):local_asr.resolve_backend()

    def test_asr_subprocess_pipeline_delayed_audio_and_hash_binding(self):
        self.fixture();before=hook.digest(self.video);backend=self.fake_backend()
        with patch.object(local_asr,'resolve_backend',return_value=backend):
            result=hook.prepare(self.args())
        self.assertEqual(result['subtitle_source'],'local_asr')
        work=self.root/'work'
        self.assertEqual(hook.read(work/'transcript.json'),hook.parse_srt(work/'transcript.srt'))
        self.assertTrue(hook.read(work/'windows.json'))
        with wave.open(str(work/'asr/audio.wav')) as w:
            self.assertEqual((w.getnchannels(),w.getframerate(),w.getsampwidth()),(1,16000,2))
            self.assertAlmostEqual(w.getnframes()/16000,hook.media_info(self.video)[2],places=3)
            samples=w.readframes(8000)
            self.assertEqual(set(samples),{0})  # initial delayed audio must remain silence
        p=hook.read(work/'plan.template.json')
        p.update(theme='fixture',theme_connection='fixture',surprise='fixture',preserved_meaning='fixture',
                 segments=[[1,2]],existing_opening={'status':'none','body_start':0})
        plan=work/'plan.json';hook.write(plan,p)
        preview=self.root/'preview'
        hook.render(argparse.Namespace(plan=plan,out=preview,max_side=160,body_seconds=2))
        hook.approve(argparse.Namespace(render=preview,quote='Synthetic fixture test approval only',opening_quote=''))
        delivery=hook.prepend(argparse.Namespace(render=preview,out=self.root/'delivery'))
        self.assertEqual(delivery['qa']['full_decode'],'passed')
        self.assertAlmostEqual(hook.parse_srt(delivery['srt'])[-1]['start'],2.6)
        self.assertEqual(hook.digest(self.video),before)
        self.assertFalse(self.video.with_suffix('.srt').exists())
        (work/'transcript.srt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'hash changed'):hook.validate_plan(plan)

    def test_asr_errors_empty_output_and_bad_timestamps_leave_diagnostics(self):
        self.fixture()
        fixtures=[('',0,'no usable'),('1\n00:00:01,000 --> 00:00:09,000\nlate\n',0,'beyond'),
                  ('1\n00:00:02,000 --> 00:00:01,000\nreversed\n',0,'no usable'),('ignored',3,'failed')]
        for i,(content,status,match) in enumerate(fixtures):
            backend=self.fake_backend(content,status)
            with patch.object(local_asr,'resolve_backend',return_value=backend):
                with self.assertRaisesRegex(ValueError,match):
                    hook.prepare(self.args(out=self.root/f'failed-{i}'))
            self.assertTrue((self.root/f'failed-{i}/asr/commands.json').exists())
            self.assertFalse((self.root/f'failed-{i}/plan.template.json').exists())

    def test_existing_output_is_never_overwritten(self):
        self.fixture();out=self.root/'work';out.mkdir();(out/'keep').write_text('keep')
        with patch.object(local_asr,'resolve_backend',return_value=self.fake_backend()), \
                patch.object(local_asr,'transcribe',side_effect=AssertionError('must not run')):
            with self.assertRaises(FileExistsError):hook.prepare(self.args())
        self.assertEqual((out/'keep').read_text(),'keep')


if __name__=='__main__':unittest.main()
