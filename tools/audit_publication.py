"""Audit only the enumerated public source and explicit release candidate.

No old application, user storage, working-tree wildcard, or credentials are read.
The existing package privacy patterns are reused from their literal declaration.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import zipfile

ROOT=Path(__file__).absolute().parents[1]
PUBLISH_EXTRA=[
    '.gitignore','.gitattributes','.github/workflows/ci.yml','.github/workflows/pages.yml',
    'website/.nojekyll','website/index.html','website/styles.css','website/app.js',
    'website/release.json','website/icon.svg','installer/install.ps1',
    'tests/test_installer.py','tests/site_browser.cjs',
]
SECRET_PATTERNS=[rb'(?i)\b(?:gh[pousr]_[a-z0-9]{30,}|github_pat_[a-z0-9_]{40,})\b',
                 rb'\bAKIA[0-9A-Z]{16}\b']
FORBIDDEN_PARTS={'data','workspace','exports','logs','models','model-cache',
                 'browser-profile','.build','__pycache__','node_modules','.git',
                 'dist','runtime','third_party','vendor'}

class AuditError(ValueError):pass

def digest(content):return hashlib.sha256(content).hexdigest()

def canonical_paths(paths):
    if len(paths)!=len(set(paths)) or len(paths)!=len({name.casefold() for name in paths}):raise AuditError('The public allowlist has duplicate or case-colliding paths.')
    for name in paths:
        p=PurePosixPath(name)
        if not name or p.is_absolute() or str(p)!=name or '\\' in name or ':' in name or '..' in p.parts or any(part in FORBIDDEN_PARTS for part in p.parts):
            raise AuditError('The public allowlist contains an unsafe or storage path.')
    return sorted(paths)

def local_path(root,name):
    canonical_paths([name])
    p=Path(root).absolute()/name
    for part in (p,*p.parents):
        try:info=part.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400 or (stat.S_ISREG(info.st_mode) and info.st_nlink>1):
            raise AuditError('Linked publication paths are refused.')
    return p

def read_source(root,name):
    p=local_path(root,name)
    try:
        with p.open('rb') as stream:content=stream.read(20*1024*1024+1)
    except OSError:raise AuditError('A required public file is missing or unreadable: '+name) from None
    if len(content)>20*1024*1024:raise AuditError('A public source file exceeds the audit size limit: '+name)
    try:content.decode('utf-8-sig')
    except UnicodeError:raise AuditError('An enumerated source file is not UTF-8 text: '+name) from None
    return content

def package_patterns(source):
    try:tree=ast.parse(source.decode('utf-8-sig'))
    except (UnicodeError,SyntaxError):raise AuditError('Cannot parse the package privacy scanner.') from None
    nodes=[node for node in ast.walk(tree) if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='forbidden' for t in node.targets)]
    if len(nodes)!=1:raise AuditError('Expected exactly one package privacy-pattern declaration.')
    try:patterns=ast.literal_eval(nodes[0].value)
    except (ValueError,TypeError):raise AuditError('The package privacy patterns must remain literal bytes.') from None
    if not isinstance(patterns,list) or not patterns or not all(isinstance(p,bytes) and p for p in patterns):
        raise AuditError('The package privacy patterns are empty or malformed.')
    for pattern in patterns:
        try:re.compile(pattern)
        except re.error:raise AuditError('A package privacy pattern is invalid.') from None
    # Ignore only the declaration itself, not the rest of the scanner's source.
    lines=source.splitlines(keepends=True);node=nodes[0]
    start=sum(len(line) for line in lines[:node.lineno-1])+node.col_offset
    end=sum(len(line) for line in lines[:node.end_lineno-1])+node.end_col_offset
    return patterns,source[:start]+source[end:]

def scan_content(name,content,patterns,scanner_body=None):
    checked=scanner_body if name=='tools/build_release.py' and scanner_body is not None else content
    if any(re.search(pattern,checked) for pattern in patterns+SECRET_PATTERNS):
        raise AuditError('Public privacy scan failed in '+name+'; no matching content is printed.')

def load_builder(root=ROOT):
    path=local_path(root,'tools/build_release.py')
    spec=importlib.util.spec_from_file_location('publication_build_release',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def source_manifest(root=ROOT,builder=None):
    builder=builder or load_builder(root)
    paths=canonical_paths(list(builder.ALLOWLIST)+PUBLISH_EXTRA)
    source=read_source(root,'tools/build_release.py')
    patterns,scanner_body=package_patterns(source)
    files=[]
    for name in paths:
        content=read_source(root,name)
        scan_content(name,content,patterns,scanner_body)
        files.append({'path':name,'bytes':len(content),'sha256':digest(content)})
    return {'scope':'Explicit public source allowlist only; no user storage traversal.',
            'files':files,'source_files':len(files),'package_privacy_patterns':len(patterns),
            'private_storage_paths_allowed':False}

def audit_git_index(root,manifest):
    run=lambda args,**kw:subprocess.run(['git','-C',str(root),*args],capture_output=True,check=True,**kw)
    try:
        top=Path(run(['rev-parse','--show-toplevel']).stdout.decode().strip()).resolve()
        if top!=Path(root).resolve():raise AuditError('Refusing a parent or unrelated Git repository.')
        entries=run(['ls-files','--stage','-z']).stdout.split(b'\0')
        indexed={}
        for entry in entries:
            if not entry:continue
            info,name=entry.split(b'\t',1);mode,sha,stage=info.decode().split()
            name=name.decode('utf-8')
            if mode not in ('100644','100755') or stage!='0' or name in indexed:raise AuditError('The Git index contains a link, conflict, or duplicate.')
            indexed[name]=sha
        expected={item['path']:item for item in manifest['files']}
        if set(indexed)!=set(expected):raise AuditError('The Git index differs from the explicit public allowlist; unapproved contents were not read.')
        for name,sha in indexed.items():
            content=run(['cat-file','blob',sha]).stdout
            if digest(content)!=expected[name]['sha256']:raise AuditError('Staged bytes differ from the audited public source: '+name)
    except (OSError,subprocess.CalledProcessError,UnicodeError):raise AuditError('Cannot verify the isolated public Git index.') from None
    return {'files':len(indexed),'exact_source_match':True}

def _pin(script,name):
    matches=re.findall(r"(?m)^\s*\$"+re.escape(name)+r"\s*=\s*'([^']+)'\s*$",script)
    if len(matches)!=1:raise AuditError('Installer must contain one literal pin for '+name+'.')
    return matches[0]

def verify_public_pins(config,installer,archive_sha,archive_name):
    required=('version','status','tag','repository_url','release_url','zip_url','checksum_url',
              'installer_url','verification_url','guide_url','issues_url','install_command',
              'zip_sha256','installer_sha256')
    if not isinstance(config,dict) or any(not isinstance(config.get(k),str) or not config[k] for k in required):
        raise AuditError('The website release configuration is incomplete.')
    if config['status']!='pre-release' or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?',config['version']):
        raise AuditError('The public version or prerelease status is invalid.')
    version=config['version'];tag='v'+version;repo=config['repository_url']
    if archive_name!='Private-Accounting-Personal-Finance-'+version+'-Windows-x64.zip':
        raise AuditError('The archive filename and public version differ.')
    if not re.fullmatch(r'https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',repo):raise AuditError('Use one canonical HTTPS GitHub repository URL.')
    download=repo+'/releases/download/'+tag+'/'
    expected={'tag':tag,'release_url':repo+'/releases/tag/'+tag,'zip_url':download+archive_name,
              'checksum_url':download+archive_name+'.sha256','installer_url':download+'install.ps1',
              'issues_url':repo+'/issues','zip_sha256':archive_sha,'installer_sha256':digest(installer)}
    if any(config[k]!=v for k,v in expected.items()):raise AuditError('Website release URLs or checksums do not match the release candidate.')
    if not config['verification_url'].startswith(download) or not config['verification_url'].endswith('.json') or '/' in config['verification_url'][len(download):]:
        raise AuditError('Verification metadata must be a same-release JSON asset.')
    if config['guide_url'] not in (repo+'/blob/'+tag+'/README.md',repo+'/blob/'+tag+'/docs/INSTALL.md'):
        raise AuditError('The setup guide must point to this release tag.')
    try:script=installer.decode('utf-8-sig')
    except UnicodeError:raise AuditError('The installer is not UTF-8 text.') from None
    if (_pin(script,'ReleaseVersion'),_pin(script,'ArchiveSha256'),_pin(script,'ReleaseUrl'))!=(version,archive_sha,expected['zip_url']):
        raise AuditError('Installer pins do not match the application ZIP.')
    command=config['install_command']
    if config['installer_url'] not in command or config['installer_sha256'] not in command:
        raise AuditError('The installation command must download and checksum this exact installer.')
    if re.search(r'(?i)\b(?:iex|invoke-expression|set-executionpolicy)\b',command):
        raise AuditError('The installation command must not pipe unverified code or change execution policy.')
    # This checks the supported bootstrap shape, not arbitrary PowerShell semantics.
    # The separate fictional bootstrap tests must prove wrong-hash code never runs.
    checks=[match.start() for match in re.finditer(r'(?i)\bget-filehash\b[^;]*?-algorithm\s+[\'\"]?sha256\b',command)]
    for created in re.finditer(r'(?i)(\$[a-z_][a-z0-9_]*)\s*=\s*\[(?:system\.)?security\.cryptography\.sha256\]\s*::\s*create\s*\(\s*\)',command):
        computed=re.search(re.escape(created.group(1))+r'\s*\.\s*ComputeHash\s*\(',command[created.end():],re.I)
        if computed:checks.append(created.end()+computed.start())
    calls=list(re.finditer(r'(?i)(?:\[(?:system\.management\.automation\.)?scriptblock\]\s*::\s*create\s*\(|&\s*\$[a-z_][a-z0-9_]*)',command))
    pin_position=command.find(config['installer_sha256'])
    if not checks or not calls or any(call.start()<min(checks) or call.start()<pin_position for call in calls):
        raise AuditError('The supported bootstrap must checksum before its script invocation.')
    return {'version':version,'repository_url':repo,'zip_sha256':archive_sha,'installer_sha256':digest(installer),'consistent':True,'bootstrap_structure_checked':True,'powershell_semantics_proven_by_static_check':False}

def audit_release(root,zip_path,builder=None):
    builder=builder or load_builder(root)
    root=Path(root).absolute();target=Path(zip_path).absolute()
    if target.parent!=root/'dist' or target.name!=builder.NAME+'.zip':raise AuditError('Audit only this publication folder\'s named dist release candidate.')
    # The path is explicit and scoped; never discover arbitrary ZIPs.
    for part in (target,*target.parents):
        try:info=part.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400 or (stat.S_ISREG(info.st_mode) and info.st_nlink>1):raise AuditError('Linked release paths are refused.')
    if target.stat().st_size>256*1024*1024:raise AuditError('Unexpected release archive size.')
    blob=target.read_bytes();prefix=builder.FOLDER+'/'
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        entries=archive.infolist();names=[i.filename for i in entries]
        if len(names)!=len(set(names)) or len(names)!=len({name.casefold() for name in names}) or len(names)>2000 or sum(i.file_size for i in entries)>256*1024*1024:raise AuditError('Unexpected or duplicate release members.')
        for entry in entries:
            if not entry.filename.startswith(prefix) or entry.file_size>50_000_000 or entry.flag_bits&1 or stat.S_ISLNK(entry.external_attr>>16):raise AuditError('Unsafe release member.')
            rel=entry.filename[len(prefix):]
            p=PurePosixPath(rel)
            if not rel or p.is_absolute() or str(p)!=rel or '..' in p.parts or '\\' in rel or ':' in rel:raise AuditError('Unsafe release member path.')
        manifest=json.loads(archive.read(prefix+'RELEASE-MANIFEST.json'))
        if manifest.get('application')!=builder.NAME or manifest.get('source_allowlist')!=builder.ALLOWLIST:raise AuditError('The archive manifest is stale or does not match the build allowlist.')
        items=manifest.get('files',[])
        if not isinstance(items,list) or len(items)!=len({i['path'] for i in items}):raise AuditError('The release manifest has duplicate entries.')
        if set(names)!={prefix+i['path'] for i in items}|{prefix+'RELEASE-MANIFEST.json'}:raise AuditError('Release members differ from the manifest.')
        for item in items:
            content=archive.read(prefix+item['path'])
            if len(content)!=item['bytes'] or digest(content)!=item['sha256']:raise AuditError('A release member differs from its manifest.')
        for rel in builder.ALLOWLIST:
            if archive.read(prefix+rel)!=read_source(root,rel):raise AuditError('Packaged source differs from the publication candidate: '+rel)
        for filename,sha in ((builder.PYTHON_ARCHIVE,builder.PYTHON_SHA),(builder.PYPDF_ARCHIVE,builder.PYPDF_SHA)):
            if digest(archive.read(prefix+'vendor/'+filename))!=sha:raise AuditError('A bundled dependency pin differs.')
    config=json.loads(read_source(root,'website/release.json'))
    tree=ast.parse(read_source(root,'app/server.py').decode('utf-8-sig'))
    versions=[ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in node.targets)]
    if versions!=[config.get('version')]:raise AuditError('The application version and website release version differ.')
    result=verify_public_pins(config,read_source(root,'installer/install.ps1'),digest(blob),target.name)
    result.update({'zip_bytes':len(blob),'members':len(names),'manifest_verified':True})
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--git-index',action='store_true')
    parser.add_argument('--release-zip',type=Path)
    args=parser.parse_args()
    try:
        builder=load_builder();result=source_manifest(builder=builder)
        if args.git_index:result['git_index']=audit_git_index(ROOT,result)
        if args.release_zip:result['release']=audit_release(ROOT,args.release_zip,builder)
        result['passed']=True;print(json.dumps(result,indent=2))
    except (AuditError,OSError,ValueError,KeyError,zipfile.BadZipFile):
        # Specific audit errors name only enumerated public files, never matching text.
        error=sys.exc_info()[1]
        print(json.dumps({'passed':False,'error':str(error) if isinstance(error,AuditError) else 'Publication audit could not verify the candidate.'}));return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
