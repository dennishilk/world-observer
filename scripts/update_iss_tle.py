#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, tempfile, urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_URL=os.environ.get('WORLD_OBSERVER_ISS_TLE_URL','https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE')
UA='world-observer-horizon/1.0 (+https://github.com/dennishilk/world-observer)'

def validate(text:str)->tuple[str,str,str]:
    lines=[l.strip() for l in text.splitlines() if l.strip()]
    if len(lines)==2: name='ISS (ZARYA)'; l1,l2=lines
    elif len(lines)>=3: name,l1,l2=lines[:3]
    else: raise ValueError('tle_requires_two_or_three_lines')
    if not l1.startswith('1 '): raise ValueError('tle_line1_prefix_invalid')
    if not l2.startswith('2 '): raise ValueError('tle_line2_prefix_invalid')
    if l1[2:7].strip()!=l2[2:7].strip(): raise ValueError('tle_catalog_id_mismatch')
    return name,l1,l2

def atomic_write(path:Path, data:str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=str(path.parent))
    with os.fdopen(fd,'w',encoding='utf-8') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def update(url:str, path:Path, timeout:float)->dict:
    req=urllib.request.Request(url, headers={'User-Agent':UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw=r.read(4096).decode('utf-8')
    name,l1,l2=validate(raw)
    payload=f'{name}\n{l1}\n{l2}\n'
    atomic_write(path,payload)
    meta={'source_url':url,'source_updated_at':datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'),'network_requests':1}
    atomic_write(Path(str(path)+'.meta.json'), json.dumps(meta,sort_keys=True)+'\n')
    return meta

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--url',default=DEFAULT_URL); ap.add_argument('--path',default='data/reference/iss.tle'); ap.add_argument('--timeout',type=float,default=10)
    a=ap.parse_args()
    try:
        meta=update(a.url,Path(a.path),a.timeout); print(json.dumps({'status':'ok',**meta},sort_keys=True))
    except Exception as e:
        print(json.dumps({'status':'failed','error':str(e),'network_requests':1},sort_keys=True)); raise SystemExit(1)
if __name__=='__main__': main()
