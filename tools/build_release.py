"""Deterministic allowlist packager. It never traverses another app or data tree."""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import re
import stat
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
NAME='Private-Accounting-Personal-Finance-1.1.0-Windows-x64'
FOLDER='PrivateAccounting'
PYTHON_ARCHIVE='python-3.14.10-embed-amd64.zip'
PYTHON_SHA='90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159'
PYPDF_ARCHIVE='pypdf-6.21.2-py3-none-any.whl'
PYPDF_SHA='1d44d1a3a200f25062adff0085b02040e4646431ac2ccac22e42679e91466084'
ALLOWLIST=[
    'README.md','LICENSE','CHANGELOG.md','THIRD-PARTY-NOTICES.md','TEST-REPORT.md',
    'Start Private Accounting.cmd','Run fictional self-tests.cmd','Create offline Sandbox configuration.cmd',
    'app/launch.py','app/server.py','app/local_model.py','app/finance_core.py','app/documents.py',
    'app/static/index.html','app/static/app.js','app/static/styles.css',
    'tests/test_finance_core.py','tests/test_documents.py','tests/test_server.py','tests/test_release_edges.py',
    'tests/browser_smoke.cjs','tests/browser_adversarial.cjs',
    'tests/test_security_stress.py','tests/test_data_stress.py','tests/test_packaging.py',
    'tests/test_bootstrap.py','tests/test_publication.py',
    'examples/fictional-transactions.csv','examples/fictional-notes.txt',
    'docs/USER-GUIDE.md','docs/PRIVACY-AND-SECURITY.md','docs/LOCAL-AI.md','docs/BACKUP-AND-RESTORE.md',
    'docs/LIMITATIONS.md','docs/TROUBLESHOOTING.md','docs/BUILD.md',
    'docs/INSTALL.md',
    'tools/build_release.py','tools/run_tests.py','tools/create_sandbox.py',
    'tools/bootstrap_runtime.py','tools/audit_publication.py',
    'licenses/CPython-SBOM.spdx.json','licenses/Python-history-and-licenses.html','licenses/Python-LICENSE.txt','licenses/pypdf-provenance.json'
]

def sha(content):return hashlib.sha256(content).hexdigest()
def safe(path):
    if path.is_absolute() or any(p in ('..','') for p in path.parts) or '\\' in str(path) or ':' in str(path):
        raise ValueError('Unsafe release archive path.')
def check_local_path(p):
    for part in (p,*p.parents):
        try:info=part.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400 or (stat.S_ISREG(info.st_mode) and info.st_nlink>1):
            raise ValueError('Linked release paths are not allowed.')
    return p
def load_allowed(rel):
    p=check_local_path(ROOT/rel)
    return p.read_bytes()
def members(blob,prefix):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for entry in z.infolist():
            if entry.is_dir():continue
            safe(PurePosixPath(entry.filename))
            if entry.file_size>50_000_000:raise ValueError('Unexpected dependency member size.')
            yield prefix+'/'+entry.filename,z.read(entry)

def build():
    files={rel:load_allowed(rel) for rel in ALLOWLIST}
    # Scan only newly authored public material, never private source trees.
    forbidden=[rb'(?i)C:[\\/]Users[\\/][^\s\\/]+',rb'(?i)client1',rb'(?i)examplefinancialstatements',rb'(?i)Accounting\.xlsx',
        rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',rb'(?i)sk-[a-z0-9]{30,}']
    # This scanner's patterns are specifications, not real secrets or identifiers.
    for rel,content in files.items():
        if rel=='tools/build_release.py' or rel.startswith('licenses/'): continue
        if any(re.search(pattern,content) for pattern in forbidden):
            raise ValueError('Public package scan failed in '+rel+'; no matching value is printed.')
    for archive,expected,prefix in ((PYTHON_ARCHIVE,PYTHON_SHA,'runtime'),(PYPDF_ARCHIVE,PYPDF_SHA,'third_party')):
        blob=load_allowed('vendor/'+archive)
        if sha(blob)!=expected:raise ValueError('Dependency digest mismatch.')
        files.update(members(blob,prefix))
        # Include pinned source archives so rebuilding this exact ZIP needs no downloads.
        files['vendor/'+archive]=blob
    manifest={'application':NAME,'source_allowlist':ALLOWLIST,'dependencies':[
        {'name':'CPython','version':'3.14.10','sha256':PYTHON_SHA},
        {'name':'pypdf','version':'6.21.2','sha256':PYPDF_SHA}],
        'files':[{'path':p,'sha256':sha(c),'bytes':len(c)} for p,c in sorted(files.items())],
        'private_data_included':False,'scan_scope':'Only explicit new source allowlist and checksum-pinned public dependencies.'}
    files['RELEASE-MANIFEST.json']=json.dumps(manifest,indent=2,ensure_ascii=False).encode('utf-8')
    dist=check_local_path(ROOT/'dist');dist.mkdir(exist_ok=True)
    target=check_local_path(dist/(NAME+'.zip'))
    temp=check_local_path(target.with_suffix('.zip.tmp'))
    check_local_path(target.with_suffix('.zip.sha256'))
    check_local_path(dist/'RELEASE-MANIFEST.json')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for rel,content in sorted(files.items()):
            safe(PurePosixPath(rel))
            info=zipfile.ZipInfo(FOLDER+'/'+rel,date_time=(2026,10,26,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16
            z.writestr(info,content,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    with zipfile.ZipFile(temp) as z:
        if z.testzip() is not None:raise ValueError('Release archive CRC verification failed.')
        if len(z.namelist())!=len(files):raise ValueError('Release member count differs.')
        for info in z.infolist():
            rel=info.filename[len(FOLDER)+1:]
            if z.read(info)!=files[rel]:raise ValueError('Release readback mismatch.')
    temp.replace(target)
    digest=sha(target.read_bytes())
    target.with_suffix('.zip.sha256').write_text(digest+'  '+target.name+'\n',encoding='ascii')
    (dist/'RELEASE-MANIFEST.json').write_bytes(files['RELEASE-MANIFEST.json'])
    print(json.dumps({'zip':str(target),'sha256':digest,'bytes':target.stat().st_size,'files':len(files),'verified':True}))

if __name__=='__main__':build()
