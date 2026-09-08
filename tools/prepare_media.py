#!/usr/bin/env python3
"""Validate and reuse private preconverted media. No downloading or synthesis."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import wave

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def prepare(source, stage, runtime, tracks=None):
    from fontTools.ttLib import TTFont
    source, stage, runtime = map(lambda p: Path(p).resolve(), (source, stage, runtime))
    if source == stage or source in stage.parents or stage in source.parents:
        raise ValueError('private source and staging must be separate')
    font = source/'CorsixTH-SC-subset.ttf'
    if not font.is_file() or font.is_symlink() or font.stat().st_size > 1024*1024:
        raise ValueError('expected regular subset font <=1 MiB')
    language = runtime/'Lua/languages/simplified_chinese.lua'
    text = language.read_text() + (runtime/'Lua/languages/english.lua').read_text()
    required = {ord(c) for c in text if c.isprintable()} | set(range(32,127))
    with TTFont(font) as face:
        missing = required - set(face.getBestCmap())
    if missing:
        raise ValueError('subset missing required characters: '+','.join(f'U+{c:04X}' for c in sorted(missing)))
    selected = sorted((source/'Music').glob('*.wav')) if tracks is None else [source/'Music'/name for name in tracks]
    if not selected or len(set(selected)) != len(selected):
        raise ValueError('require a nonempty, nonduplicate WAV selection')
    files=[(font,Path(font.name))]; rows=[]
    for path in selected:
        if path.parent != source/'Music' or path.is_symlink() or not path.is_file() or path.suffix.lower() != '.wav':
            raise ValueError('track must be a regular WAV directly in Music')
        with wave.open(str(path),'rb') as stream:
            if (stream.getnchannels(),stream.getsampwidth(),stream.getframerate(),stream.getcomptype()) != (1,2,22050,'NONE'):
                raise ValueError('3DS baseline music requires PCM16 mono 22050 Hz: '+path.name)
            frames=stream.getnframes()
            if not frames:raise ValueError('empty music: '+path.name)
            # Check the complete declared stream in bounded host chunks.
            remaining=frames
            while remaining:
                n=min(16384,remaining)
                if len(stream.readframes(n)) != n*2:raise ValueError('truncated music: '+path.name)
                remaining-=n
        files.append((path,Path('Music')/path.name))
        rows.append({'name':path.name,'frames':frames,'sample_rate':22050,'channels':1,'bits':16})
    inventory=[]
    for path, relative in files:
        digest=sha(path);dest=stage/relative
        if dest.is_symlink():raise ValueError('staged media may not be a symlink')
        if dest.exists():
            if sha(dest)!=digest:raise ValueError('refusing to overwrite different staged media: '+str(relative))
        else:
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
        if sha(dest)!=digest:raise ValueError('copied media differs')
        inventory.append({'path':relative.as_posix(),'bytes':path.stat().st_size,'sha256':digest})
    report={'schema':'corsixth.private-media.v1','files':inventory,'music':rows,
            'required_characters':len(required),'missing_characters':0,
            'font_rendering':'upstream FreeType -> real render_target -> selected backend',
            'music_transport':'file-backed SDL_mixer WAV; one active decoder',
            'redistribution':'PRIVATE_USER_ASSETS_ONLY','device':'NOT_PROVEN'}
    (stage/'private-media.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','stage','runtime'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--track',action='append',help='one WAV name; repeat, defaults to all prepared tracks')
    args=parser.parse_args()
    try:
        report=prepare(args.source,args.stage,args.runtime,args.track)
        print(json.dumps(report,ensure_ascii=False,indent=2))
    except (OSError,ValueError,wave.Error,ImportError) as e:parser.exit(2,str(e)+'\n')

if __name__=='__main__':main()
