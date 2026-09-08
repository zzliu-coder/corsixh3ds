#!/usr/bin/env python3
"""Private offline voice conversion. Exact DAT indices, aliases and event names."""
import argparse,ctypes,hashlib,io,json,struct,wave
from pathlib import Path
from prepare_loose_assets import parse_original_sound
from th3ds_resource import ResourceError

LANGUAGES={'zh':'CN','en':'EN','fr':'FR','de':'DE','it':'IT','es':'ES','sv':'SV'}
def sha(data):return hashlib.sha256(data).hexdigest()
def converter(library):
    lib=ctypes.CDLL(str(library))
    fn=lib.voice_pcm;fn.restype=ctypes.c_int
    fn.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_void_p,ctypes.c_int]
    def convert(sound):
        if sound.bits_per_sample==16 and sound.sample_rate==22050:return sound.pcm
        source=ctypes.create_string_buffer(sound.pcm)
        args=(source,len(sound.pcm),sound.bits_per_sample,sound.channels,sound.sample_rate)
        size=fn(*args,None,0)
        if size<=0 or size>12*1024*1024:raise ResourceError('voice conversion allocation rejected')
        output=ctypes.create_string_buffer(size);length=fn(*args,output,size)
        if length<=0:raise ResourceError('SDL voice conversion failed')
        return output.raw[:length]
    return convert

def convert_bank(data,convert,cache,replacements=None):
    sounds,indices,reserved=parse_original_sound(data)
    if not reserved or indices!=list(range(1,len(sounds)+1)):
        raise ResourceError('voice bank must retain original reserved slot zero')
    hp=struct.unpack_from('<I',data,len(data)-4)[0]
    tp=struct.unpack_from('<I',data,hp+50)[0]
    count=len(sounds)+1;table=bytearray(data[tp:tp+count*32])
    table[:32]=bytes(32);payload=bytearray();locations={};rows=[]
    for index,sound in zip(indices,sounds):
        if replacements and index in replacements:
            alternate=replacements[index]
            if alternate.name.casefold()!=sound.name.casefold():
                raise ResourceError('voice event name differs')
            sound=alternate
        key=(sound.channels,sound.sample_rate,sound.bits_per_sample,sha(sound.pcm))
        if key not in cache:cache[key]=convert(sound)
        pcm=cache[key];frames=len(pcm)//(sound.channels*2)
        source_frames=len(sound.pcm)//(sound.channels*(sound.bits_per_sample//8))
        expected=source_frames*22050//sound.sample_rate
        if abs(frames-expected)>1 or frames<=0:
            raise ResourceError('converted voice duration differs: '+sound.name)
        if (frames+64)*4+count*128+8192>3*1024*1024:
            raise ResourceError('converted voice exceeds actual sound cache budget: '+sound.name)
        # Native DAT permits exact same-name aliases only. Keep separate names
        # in separate payload ranges even when their decoded samples coincide.
        identity=(sound.name.casefold(),key)
        if identity not in locations:
            output=io.BytesIO()
            with wave.open(output,'wb') as w:
                w.setparams((sound.channels,2,22050,0,'NONE','not compressed'));w.writeframes(pcm)
            encoded=output.getvalue();locations[identity]=(len(payload),len(encoded))
            payload.extend(encoded)
        pos,length=locations[identity]
        struct.pack_into('<I',table,index*32+18,pos)
        struct.pack_into('<I',table,index*32+26,length)
        rows.append(dict(index=index,name=sound.name,channels=sound.channels,frames=frames,
                         pcm_sha256=sha(pcm),source_pcm_sha256=sha(sound.pcm),
                         converted=(sound.sample_rate!=22050 or sound.bits_per_sample!=16)))
    new_table=len(payload);payload.extend(table)
    new_header=len(payload);header=bytearray(data[hp:hp+234])
    struct.pack_into('<I',header,50,new_table);struct.pack_into('<I',header,58,len(table))
    payload.extend(header);payload.extend(struct.pack('<I',new_header))
    encoded=bytes(payload);decoded,new_indices,new_reserved=parse_original_sound(encoded)
    if new_indices!=indices or new_reserved!=reserved:raise ResourceError('voice index changed')
    for item,row in zip(decoded,rows):
        if (item.name!=row['name'] or item.channels!=row['channels'] or
            item.sample_rate!=22050 or item.bits_per_sample!=16 or sha(item.pcm)!=row['pcm_sha256']):
            raise ResourceError('voice output reparse differs')
    return encoded,rows

def prepare(banks,stage,library):
    stage=Path(stage).resolve();convert=converter(library);cache={};files=[];reports=[]
    sources={}
    for code,path in banks.items():
        if code not in LANGUAGES:raise ResourceError('unknown voice language')
        path=Path(path)
        if not path.is_file() or path.is_symlink() or path.stat().st_size>64*1024*1024:
            raise ResourceError('voice source must be a regular bank <=64 MiB')
        if path.resolve()==stage or stage in path.resolve().parents:
            raise ResourceError('voice input overlaps output')
        sources[code]=(path,path.read_bytes())
    # Keep canonical English game SFX/indices for every voice. Other original
    # editions contain differently named non-speech effects; never substitute
    # those into a voice-only switch. The supplied Chinese patch identifies
    # the speech entries by exact same-name PCM differences from English.
    if 'en' not in sources or 'zh' not in sources:
        raise ResourceError('canonical English and Chinese patch banks are required')
    canonical,canonical_ids,_=parse_original_sound(sources['en'][1])
    chinese,chinese_ids,_=parse_original_sound(sources['zh'][1])
    if canonical_ids!=chinese_ids or [s.name.lower()for s in canonical]!=[s.name.lower()for s in chinese]:
        raise ResourceError('Chinese patch event indices differ from canonical English')
    speech={i:s.name.lower()for i,s,z in zip(canonical_ids,canonical,chinese)
            if (s.pcm,s.channels,s.sample_rate,s.bits_per_sample)!=(z.pcm,z.channels,z.sample_rate,z.bits_per_sample)}
    if not speech:raise ResourceError('Chinese patch contains no changed speech')
    for code,(path,data) in sources.items():
        replacements={}
        if code!='en':
            parsed,_,_=parse_original_sound(data);by_name={s.name.lower():s for s in parsed}
            missing=set(speech.values())-set(by_name)
            if missing:raise ResourceError('voice events missing: '+code+' '+str(sorted(missing)))
            replacements={i:by_name[name]for i,name in speech.items()}
        output,rows=convert_bank(sources['en'][1],convert,cache,replacements)
        relative='Voices/Sound-'+LANGUAGES[code]+'.dat';dest=stage/relative
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.is_symlink():raise ResourceError('voice output may not be a symlink')
        if dest.exists():
            if dest.read_bytes()!=output:raise ResourceError('refuse different prepared voice output')
        else:dest.write_bytes(output)
        files.append(dict(path=relative,bytes=len(output),sha256=sha(output)))
        reports.append(dict(code=code,source=str(path.resolve()),source_sha256=sha(data),
                            output=relative,slots=len(rows)+1,entries=rows,
                            speech_slots=sorted(speech),canonical_effects_source_sha256=sha(sources['en'][1])))
        print(code+' voice prepared '+str(len(output))+' bytes; indices unchanged',flush=True)
    if any(path.read_bytes()!=data for path,data in sources.values()):
        raise ResourceError('voice source changed during conversion')
    report=dict(schema='corsixth.private-voices.v1',format='PCM S16LE 22050 Hz; original mono/stereo',
                files=files,banks=reports,default='zh' if 'zh' in sources else 'en',
                converter_sha256=sha(Path(library).read_bytes()),
                source_code_sha256=sha(Path(__file__).read_bytes()),device='NOT_PROVEN')
    receipt=stage/'voice-manifest.json'
    serialized=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if receipt.is_symlink():raise ResourceError('voice receipt may not be a symlink')
    # All payloads were just reparsed and matched byte for byte. Refresh the
    # recipe receipt when converter code changes without recopying the banks.
    receipt.write_text(serialized)
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bank',action='append',required=True,help='language=source.dat; repeat')
    p.add_argument('--stage',type=Path,required=True);p.add_argument('--converter',type=Path,required=True)
    a=p.parse_args();banks={}
    for item in a.bank:
        code,path=item.split('=',1)
        if code in banks:p.error('duplicate language')
        banks[code]=Path(path)
    prepare(banks,a.stage,a.converter)
if __name__=='__main__':main()
