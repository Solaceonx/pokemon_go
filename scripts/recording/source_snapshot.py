"""Keep the exact source bytes behind recorded processing fingerprints.

Git checkout newline conversion must not make an old detector irreproducible.
These small text-only archives preserve UTF-8 source bytes, not media or OCR.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath


def safe_name(name):
    if (not isinstance(name,str) or not name or '\\' in name or ':' in name
            or PurePosixPath(name).is_absolute() or any(p in ('','.','..') for p in name.split('/'))):
        raise ValueError('Snapshot paths must be ordinary relative paths')
    return name


def create(root, manifest, output):
    files=[]
    for name, expected in sorted(manifest.items()):
        name=safe_name(name);raw=(root/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:
            raise ValueError('Source bytes differ from the pinned manifest: '+name)
        files.append(dict(path=name,sha256=expected,source_utf8=raw.decode('utf-8')))
    document=dict(schema='task46-source-snapshot-v1',hash_basis='Exact UTF-8 bytes including original newlines',files=files)
    packed=gzip.compress((json.dumps(document,ensure_ascii=True,separators=(',',':'))+'\n').encode('utf-8'),mtime=0)
    if output.exists():
        if output.read_bytes()!=packed:raise ValueError('Refusing to replace a different source snapshot')
    else:
        output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(packed)
    return verify(output)


def verify(archive):
    document=json.loads(gzip.decompress(archive.read_bytes()))
    if document.get('schema')!='task46-source-snapshot-v1':raise ValueError('Unknown source snapshot schema')
    files={}
    for entry in document['files']:
        name=safe_name(entry['path'])
        if name in files:raise ValueError('Duplicate source path')
        raw=entry['source_utf8'].encode('utf-8')
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Source checksum mismatch: '+name)
        files[name]=raw
    if not files:raise ValueError('Empty source snapshot')
    return files


def extract(archive,destination):
    files=verify(archive)
    if destination.exists() or destination.is_symlink():raise ValueError('Extraction needs a new destination directory')
    destination.mkdir(parents=True)
    for name,raw in files.items():
        path=destination/name
        if not path.resolve().is_relative_to(destination.resolve()):raise ValueError('Source path escaped destination')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    return len(files)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('create','verify','extract'))
    parser.add_argument('archive',type=Path)
    parser.add_argument('--root',type=Path,default=Path('.'))
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--destination',type=Path)
    args=parser.parse_args()
    if args.action=='create':
        if args.manifest is None:parser.error('create requires --manifest')
        count=len(create(args.root,json.loads(args.manifest.read_text(encoding='utf8')),args.archive))
    elif args.action=='extract':
        if args.destination is None:parser.error('extract requires --destination')
        count=extract(args.archive,args.destination)
    else:count=len(verify(args.archive))
    print(json.dumps(dict(action=args.action,verified_source_files=count)))


if __name__=='__main__':main()
