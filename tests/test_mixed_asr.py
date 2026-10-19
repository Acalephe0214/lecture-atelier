"""Synthetic routing checks only: these do not measure real speech accuracy."""
import json
from pathlib import Path
import sys
import tempfile
import wave
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.languages import language, candidates, decoder_language, check_model, LanguageUncertain
from core.mixed_asr import choose_language, decode_mixed, transcribe_mlx
from core.asr_guard import guarded_window


class Audio:
    """Tiny constant-valued numpy-like slice with source coordinates."""
    def __init__(self, length, start=0, level=.1):
        self.length, self.start, self.level = length, start, level
    def __len__(self): return self.length
    def __getitem__(self, key):
        a, b, step = key.indices(self.length)
        assert step == 1
        return Audio(b-a, self.start+a, self.level)
    def __abs__(self): return self
    def max(self): return self.level
    def astype(self, dtype): return self
    def __truediv__(self, divisor): return self


class MixedLanguageTests(unittest.TestCase):
    def test_normalization_and_legacy(self):
        self.assertEqual(language('mix:vi,fr'), 'mix:fr,vi')
        self.assertEqual(candidates('mix:vi,fr'), ('fr', 'vi'))
        self.assertEqual(candidates('zh_en'), ('en', 'zh'))
        self.assertEqual(language('zh_en'), 'zh_en')
        self.assertIsNone(decoder_language('mix:fr,vi'))
        self.assertEqual(decoder_language('fr'), 'fr')

    def test_invalid_combinations(self):
        for value in ('mix:fr', 'mix:fr,fr', 'mix:fr,auto', 'mix:fr,zzz', 'mix:en,zh,fr,vi,de,ja,es'):
            with self.subTest(value=value), self.assertRaises(ValueError): language(value)

    def test_model_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps({'n_vocab': 51864}))
            with self.assertRaisesRegex(ValueError, '英语专用'): check_model({'model_path':folder, 'language':'mix:fr,vi'})
            path.write_text(json.dumps({'n_vocab': 51865}))
            with self.assertRaisesRegex(ValueError, '粤语'): check_model({'model_path':folder, 'language':'mix:en,yue'})
            check_model({'model_path':folder, 'language':'mix:fr,vi'})

    def test_probability_gates(self):
        self.assertEqual(choose_language([('fr', .7), ('vi', .2)], ('fr','vi')), 'fr')
        for scores in ({'fr':.1,'vi':.1}, {'en':.8,'fr':.15,'vi':.05}, {}, {'fr':float('nan')}):
            with self.subTest(scores=scores), self.assertRaises(LanguageUncertain): choose_language(scores, ('fr','vi'))

    def test_windows_context_words_and_heartbeat(self):
        selected, beats = [], []
        def detect(audio): return {'fr':.8,'vi':.1} if audio.start == 0 else {'fr':.1,'vi':.8}
        def recognize(audio, lang):
            selected.append((audio.start, len(audio), lang))
            # First window's tail is context from the next core and must drop.
            words = ([{'start':0,'end':1,'word':'Bonjour'}, {'start':12,'end':13,'word':'DROP'}]
                     if lang == 'fr' else [{'start':0,'end':1,'word':'DROP'}, {'start':1,'end':2,'word':'Xin'}, {'start':2,'end':3,'word':'chào'}])
            return {'segments':[{'words':words,'avg_logprob':-.2}]}
        result = decode_mixed(Audio(24*16000), ('fr','vi'), detect, recognize, keep_words=True, on_window=lambda *a:beats.append(a))
        self.assertEqual([r['text'] for r in result['segments']], ['Bonjour','Xin chào'])
        self.assertEqual(result['segments'][1]['start'], 12)
        self.assertEqual(result['segments'][1]['end'], 14)
        self.assertEqual(selected, [(0,13*16000,'fr'),(11*16000,13*16000,'vi')])
        self.assertEqual(beats, [(0,12),(12,12)])
        self.assertEqual(result['segments'][1]['words'][0]['start'],12)

    def test_silence_and_missing_words(self):
        def forbidden(*args): self.fail('silence should not invoke a model')
        self.assertTrue(decode_mixed(Audio(16000,level=0),('fr','vi'),forbidden,forbidden)['digital_silence'])
        with self.assertRaises(LanguageUncertain):
            decode_mixed(Audio(16000),('fr','vi'),lambda a:{'fr':.9},lambda a,l:{'segments':[{'text':'invented'}]})

    def test_uncertain_audio_remains_gap(self):
        def decode(*args): raise LanguageUncertain()
        result = guarded_window(decode, 0, 60)
        self.assertTrue(result['issues'])
        self.assertIn('混合语言',str(result))
        self.assertFalse(result['segments'])

    def test_cpu_integration_forces_audio_selected_language_and_word_times(self):
        from core import local_engine
        seen = []
        model = SimpleNamespace(detect_language=lambda **kw:('fr',.9,[('fr',.9),('vi',.05)]))
        def recognize(audio, **kwargs):
            seen.append(kwargs)
            row = SimpleNamespace(start=0,end=1,text='Bonjour',avg_logprob=-.1,compression_ratio=1,no_speech_prob=.01, words=[SimpleNamespace(start=0,end=1,word='Bonjour')])
            return iter([row]), None
        model.transcribe = recognize
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'tokenizer.json').write_text('{}')
            with patch.dict(sys.modules, {'faster_whisper':SimpleNamespace(WhisperModel=lambda *a,**k:model)}), patch.object(local_engine,'_model',None), patch.object(local_engine,'audio_window',return_value=Audio(16000)):
                result=local_engine.transcribe({'backend':'faster','model_path':folder,'language':'mix:fr,vi'},'unused',0,1)
        self.assertEqual(result['segments'][0]['text'],'Bonjour')
        self.assertEqual(seen[0]['language'],'fr')
        self.assertTrue(seen[0]['word_timestamps'])
        self.assertFalse(seen[0]['condition_on_previous_text'])

    def test_mlx_single_language_unchanged(self):
        calls=[]
        fake=SimpleNamespace(transcribe=lambda *a,**k:calls.append((a,k)) or {'segments':[]})
        with patch.dict(sys.modules,{'mlx_whisper':fake}):
            transcribe_mlx('local.wav',{'model_path':'local-model','language':'fr'},word_timestamps=True)
        self.assertEqual(calls[0][1]['language'],'fr')
        self.assertEqual(calls[0][1]['task'],'transcribe')

    def test_mlx_mixed_uses_local_holder_audio_scores_and_word_times(self):
        calls=[]
        def recognize(audio, **kwargs):
            calls.append(kwargs)
            return {'segments':[{'words':[{'start':0,'end':1,'word':'Bonjour'}]}]}
        model=SimpleNamespace(dims=SimpleNamespace(n_mels=80),detect_language=lambda mel:(0,{'fr':.9,'vi':.05}))
        holder=SimpleNamespace(get_model=lambda path,dtype:model)
        mx=SimpleNamespace(float16='float16')
        modules={'mlx_whisper':SimpleNamespace(transcribe=recognize),
                 'mlx':SimpleNamespace(core=mx),'mlx.core':mx,
                 'mlx_whisper.transcribe':SimpleNamespace(ModelHolder=holder),
                 'mlx_whisper.audio':SimpleNamespace(log_mel_spectrogram=lambda audio,**k:audio,pad_or_trim=lambda mel,*a,**k:mel,N_FRAMES=3000,N_SAMPLES=480000),
                 'numpy':SimpleNamespace(frombuffer=lambda data,**k:Audio(len(data)//2),float32='float32')}
        with tempfile.TemporaryDirectory() as folder:
            filename=str(Path(folder)/'chunk.wav')
            with wave.open(filename,'wb') as handle:
                handle.setparams((1,2,16000,0,'NONE','not compressed'))
                handle.writeframes(b'\x00\x00'*16000)
            with patch.dict(sys.modules,modules):
                result=transcribe_mlx(filename,{'language':'mix:fr,vi','model_path':'local-model'},word_timestamps=True)
        self.assertEqual(result['segments'][0]['text'],'Bonjour')
        self.assertEqual(calls[0]['language'],'fr')
        self.assertTrue(calls[0]['word_timestamps'])
        self.assertEqual(calls[0]['path_or_hf_repo'],'local-model')

    def test_checkpoint_version_changes_mixed_only(self):
        from asr_checkpoints import Checkpoints
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'config.json').write_text('{}')
            cfg={'model_path':folder,'language':'zh'}
            single=Checkpoints.key('id','src',cfg)
            mixed=Checkpoints.key('id','src',{**cfg,'language':'zh_en'})
            with patch('core.mixed_asr.VERSION','future-strategy'):
                self.assertEqual(single,Checkpoints.key('id','src',cfg))
                self.assertNotEqual(mixed,Checkpoints.key('id','src',{**cfg,'language':'zh_en'}))


if __name__ == '__main__': unittest.main()
