"""Prepare checksum-pinned local dependencies. Network requires explicit --download."""
from pathlib import Path
import argparse
import hashlib
import io
import os
import sys
import tempfile
import time
import urllib.request
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from build_release import (ROOT, PYTHON_ARCHIVE, PYTHON_SHA, PYPDF_ARCHIVE,
                           PYPDF_SHA, check_local_path, members)

SOURCES=(
    (PYTHON_ARCHIVE,PYTHON_SHA,'runtime','https://www.python.org/ftp/python/3.14.10/'+PYTHON_ARCHIVE),
    (PYPDF_ARCHIVE,PYPDF_SHA,'third_party','https://files.pythonhosted.org/packages/1b/4d/c9d2d67f204eff463237a1a8f5e25a6923b7b1043982b91fcaf104c8ef60/'+PYPDF_ARCHIVE),
)
MAX_ARCHIVE=32*1024*1024

def publish_directory(staging,destination):
    # Windows scanners may briefly hold a newly written DLL/package directory.
    # Retry a non-overwriting rename; never remove or replace a destination.
    for attempt in range(20):
        check_local_path(destination)
        if destination.exists():raise ValueError('Dependency destination appeared while preparing it; preserved.')
        try:
            os.rename(staging,destination)
            return
        except PermissionError:
            if attempt==19:raise
            time.sleep(.1)

def prepare(root=ROOT,download=False):
    root=check_local_path(Path(root).absolute())
    vendor=check_local_path(root/'vendor');vendor.mkdir(exist_ok=True)
    for name,digest,prefix,url in SOURCES:
        archive=check_local_path(vendor/name)
        if archive.exists():
            with archive.open('rb') as stream:blob=stream.read(MAX_ARCHIVE+1)
        elif download:
            request=urllib.request.Request(url,headers={'User-Agent':'Private-Accounting-dependency-bootstrap'})
            with urllib.request.urlopen(request,timeout=60) as response:
                if not response.geturl().startswith('https://'):raise ValueError('Dependency transport must remain HTTPS.')
                blob=response.read(MAX_ARCHIVE+1)
        else:
            raise ValueError('Pinned archives are missing. Use --download explicitly, or supply the verified vendor archives from the release ZIP.')
        if len(blob)>MAX_ARCHIVE or hashlib.sha256(blob).hexdigest()!=digest:
            raise ValueError('Dependency checksum/size mismatch; existing files were preserved.')
        entries=list(members(blob,prefix))
        destination=check_local_path(root/prefix)
        if destination.exists():
            for rel,content in entries:
                existing=check_local_path(root/rel)
                if not existing.is_file() or hashlib.sha256(existing.read_bytes()).digest()!=hashlib.sha256(content).digest():
                    raise ValueError('Existing dependency folder differs. Preserve it and use a fresh clone or extraction.')
        else:
            with tempfile.TemporaryDirectory(dir=root,prefix='.bootstrap-') as temporary:
                if not Path(temporary).resolve().is_relative_to(root.resolve()):raise ValueError('Unexpected staging location.')
                staging=Path(temporary)/prefix;staging.mkdir()
                for rel,content in entries:
                    relative=Path(rel).relative_to(prefix)
                    target=staging/relative;target.parent.mkdir(parents=True,exist_ok=True)
                    with target.open('xb') as stream:stream.write(content)
                publish_directory(staging,destination)
        if not archive.exists():
            with archive.open('xb') as stream:stream.write(blob)
    return {'prepared':True,'download_authorized':download}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download',action='store_true',help='Explicitly download the pinned public dependency archives if missing.')
    args=parser.parse_args()
    try:
        prepare(download=args.download)
        print('Pinned runtime and PDF dependencies verified and ready.')
    except (OSError,ValueError,zipfile.BadZipFile) as error:
        raise SystemExit(str(error)) from None
