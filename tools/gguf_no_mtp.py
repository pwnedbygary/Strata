#!/usr/bin/env python3
"""Add an explicit zero-MTP field to a 40-layer qwen35moe GGUF, without changing tensors."""
import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.gguf_reader import GGUFFile


def convert(source, target):
    source,target=Path(source),Path(target)
    g=GGUFFile(source)
    key='qwen35moe.nextn_predict_layers'
    if g.metadata.get('general.architecture')!='qwen35moe' or g.metadata.get('qwen35moe.block_count')!=40:
        raise ValueError('only the 40-layer qwen35moe no-MTP case is supported')
    if key in g.metadata or any(t.name.startswith('blk.40.') for t in g.tensors):
        raise ValueError('MTP metadata already exists or an MTP tensor is present')
    if g.metadata.get('split.count',1)!=1:
        raise ValueError('split GGUFs need a separate shard-aware adapter')
    if source.resolve()==target.resolve():raise ValueError('use a separate output')
    with source.open('rb') as original:
        head=original.read(24);_,_,nt,nk=struct.unpack('<IIQQ',head)
        for _ in range(nk):g._str(original);g._value(original)
        kv_end=original.tell()
        for _ in range(nt):
            g._str(original);nd=struct.unpack('<I',original.read(4))[0];original.seek(8*nd+12,1)
        tensor_end=original.tell();original.seek(0);prefix=bytearray(original.read(tensor_end))
        struct.pack_into('<Q',prefix,16,nk+1)
        entry=struct.pack('<Q',len(key))+key.encode()+struct.pack('<II',4,0)
        new_start=(tensor_end+len(entry)+g.alignment-1)//g.alignment*g.alignment
        digest=hashlib.sha256()
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'wb') as out:
                out.write(prefix[:kv_end]);out.write(entry);out.write(prefix[kv_end:])
                out.write(b'\0'*(new_start-tensor_end-len(entry)));original.seek(g.data_start)
                while chunk:=original.read(8*2**20):out.write(chunk);digest.update(chunk)
            converted=GGUFFile(target)
            assert converted.metadata[key]==0 and converted.tensors==g.tensors
            verify=hashlib.sha256()
            with target.open('rb') as out:
                out.seek(converted.data_start)
                while chunk:=out.read(8*2**20):verify.update(chunk)
            if verify.digest()!=digest.digest():raise ValueError('tensor payload changed')
            manifest={'source':source.name,'output':target.name,'added_metadata':{key:0},
                      'source_data_start':g.data_start,'output_data_start':converted.data_start,
                      'tensor_payload_sha256':digest.hexdigest(),'tensor_payload_identical':True}
            target.with_suffix(target.suffix+'.compat.json').write_text(json.dumps(manifest,indent=2)+'\n')
            return manifest
        except BaseException:
            target.unlink(missing_ok=True);raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();print(json.dumps(convert(a.source,a.output),indent=2))
