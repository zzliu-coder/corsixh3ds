"""Generate synthetic WAV/DAT inputs only; no copyrighted game resources."""
import struct
from pathlib import Path


def wave(n: int, value: int) -> bytes:
    pcm=bytes([value&255])*n
    fmt=struct.pack('<HHIIHH',1,1,22050,22050,1,8)
    body=b'WAVEfmt '+struct.pack('<I',len(fmt))+fmt+b'data'+struct.pack('<I',len(pcm))+pcm
    if len(pcm)&1:body+=b'\0'
    return b'RIFF'+struct.pack('<I',len(body))+body


def archive(waves: list[bytes]) -> bytes:
    payload=bytearray()
    entries=[bytes(32)]
    for i,w in enumerate(waves,1):
        name=f'S{i:04}.WAV'.encode().ljust(18,b'\0')
        entries.append(name+struct.pack('<I',len(payload))+bytes(4)+struct.pack('<I',len(w))+bytes(2))
        payload.extend(w)
    table=len(payload);payload.extend(b''.join(entries));header=len(payload)
    h=bytearray(234);struct.pack_into('<I',h,50,table);struct.pack_into('<I',h,58,len(entries)*32)
    payload.extend(h);payload.extend(struct.pack('<I',header));return bytes(payload)


def make(root: Path) -> None:
    root.mkdir(parents=True,exist_ok=True)
    a=archive([wave(400,0x81),wave(720,0x85)])
    (root/'a.dat').write_bytes(a)
    (root/'b.dat').write_bytes(archive([wave(820,0x91)]))
    (root/'747.dat').write_bytes(archive([wave(180+(i%7)*2,128+i%4) for i in range(746)]))
    (root/'large.dat').write_bytes(archive([wave(100000,128+i%4) for i in range(40)]))
    (root/'truncated.dat').write_bytes(a[:-20])
    header=struct.unpack_from('<I',a,len(a)-4)[0];table=struct.unpack_from('<I',a,header+50)[0]
    bad=bytearray(a);struct.pack_into('<I',bad,table+64+18,1);(root/'overlap.dat').write_bytes(bad)
    bad=bytearray(a);bad[table+64:table+82]=bad[table+32:table+50];(root/'conflicting.dat').write_bytes(bad)
    alias=bytearray(a);alias[table+64:table+96]=alias[table+32:table+64];(root/'alias.dat').write_bytes(alias)
    (root/'invalid-wave.dat').write_bytes(archive([b'X'*44]))

if __name__=='__main__':
    import sys
    make(Path(sys.argv[1]))
