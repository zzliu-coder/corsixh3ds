"""Language closure and original DAT metadata validation, including aliases."""
import hashlib
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from prepare_loose_assets import prepare, parse_original_sound
from th3ds_resource import ResourceError
from test_th3ds_resource_packer import make_fixture, sound_archive, pcm_wave


def add_loose_fixture(package, root):
    from test_playable_path import original_sources
    source,_,_=make_fixture(root/'asset-input')
    runtime=original_sources(root/'runtime-input')/'CorsixTH'
    if (package/'game').exists(): shutil.rmtree(package/'game')
    shutil.copytree(source,package/'game')
    prepare(runtime,source,package)


class PlayableAssetsTests(unittest.TestCase):
    def test_real_upstream_english_closure_is_staged_without_mutating_source(self):
        from test_playable_path import original_sources
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source,_,_=make_fixture(root/'input')
            runtime=original_sources(root/'runtime')/'CorsixTH'
            (runtime/'Lua/languages/unused.lua').write_text('Language("Unused")\n')
            before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
            stage=root/'stage';shutil.copytree(source,stage/'game')
            shutil.copytree(runtime/'Lua/languages',stage/'Lua/languages')
            result=prepare(runtime,source,stage)
            self.assertEqual(set(result['language_files']),{'english.lua','original_strings.lua'})
            self.assertEqual(result['original_string_ids'],[0])
            self.assertEqual(result['sound_source_sha256'],result['sound_staged_sha256'])
            self.assertEqual(before,{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()})
            self.assertEqual({p.name for p in (stage/'Lua/languages').glob('*.lua')},{'english.lua','original_strings.lua'})

    def test_conflicting_alias_partial_overlap_and_truncation_fail(self):
        raw=sound_archive([('A.WAV',pcm_wave(bytes(100))),('B.WAV',pcm_wave(bytes(100)))])
        h=struct.unpack_from('<I',raw,len(raw)-4)[0];t=struct.unpack_from('<I',raw,h+50)[0]
        bad=bytearray(raw);bad[t+32:t+50]=bad[t:t+18]
        with self.assertRaises(ResourceError):parse_original_sound(bytes(bad))
        bad=bytearray(raw);struct.pack_into('<I',bad,t+32+18,4)
        with self.assertRaises(ResourceError):parse_original_sound(bytes(bad))
        with self.assertRaises(ResourceError):parse_original_sound(raw[:-10])

    def test_exact_original_alias_retains_numeric_index(self):
        raw=bytearray(sound_archive([('A.WAV',pcm_wave(bytes(100))),('B.WAV',pcm_wave(bytes(100)))]))
        h=struct.unpack_from('<I',raw,len(raw)-4)[0];t=struct.unpack_from('<I',raw,h+50)[0]
        raw[t+32:t+64]=raw[t:t+32]
        sounds,indices,reserved=parse_original_sound(bytes(raw))
        self.assertEqual(indices,[0,1]);self.assertEqual(sounds[0],sounds[1]);self.assertEqual(reserved,0)

    def test_language_missing_original_and_oversized_required_sound_fail(self):
        from test_playable_path import original_sources
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source,_,_=make_fixture(root/'input');runtime=original_sources(root/'runtime')/'CorsixTH'
            stage=root/'stage';shutil.copytree(source,stage/'game')
            data=source/'DATA/LANG-0.DAT';saved=data.read_bytes();data.unlink()
            with self.assertRaises(ResourceError):prepare(runtime,source,stage)
            data.write_bytes(saved)
            (source/'SOUND/DATA/SOUND-0.DAT').write_bytes(sound_archive([('BIG.WAV',pcm_wave(bytes(2*1024*1024)))]))
            with self.assertRaises(ResourceError):prepare(runtime,source,stage)
