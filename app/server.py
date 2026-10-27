"""Loopback-only personal finance HTTP service. No request-body/access logging."""
from __future__ import annotations
import base64
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import select
import secrets
import socket
import stat
import threading
import time
import uuid
import zipfile
from finance_core import Store, FinanceError
from documents import preview_file, xlsx_bytes, csv_bytes, report_html
from local_model import LocalModel, ModelError

VERSION='1.1.0'
MAX_BODY=15_000_000
MAX_BACKUP_BYTES=128*1024*1024
MAX_BACKUP_FILES=20000
MAX_DOWNLOADS=100
MAX_CONNECTIONS=16
SOCKET_TIMEOUT=15
STATIC=Path(__file__).parent/'static'

def json_bytes(data):
    return json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')

def safe_name(name):
    if not isinstance(name,str) or not name or len(name)>200 or any(c in name for c in '/\\:\x00') or name in ('.','..') or name.endswith((' ','.')):
        raise ValueError('Use a simple filename without a path.')
    return name

def check_local(path):
    path=Path(path).absolute()
    if str(path).startswith(('\\\\','//')): raise ValueError('Only local disk storage is supported.')
    for part in (path,*path.parents):
        try: info=part.lstat()
        except FileNotFoundError: continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400 or (stat.S_ISREG(info.st_mode) and info.st_nlink>1):
            raise ValueError('Linked or redirected storage paths are refused.')
    return path

def read_limited(path,limit=10_000_000):
    check_local(path)
    with Path(path).open('rb') as stream: content=stream.read(limit+1)
    if len(content)>limit: raise ValueError('Stored file exceeds the supported limit.')
    return content

def owned_files(folder):
    check_local(folder)
    if not folder.exists(): return
    for parent,dirs,files in os.walk(folder,followlinks=False):
        for name in dirs+files: check_local(Path(parent)/name)
        for name in files: yield Path(parent)/name

def write_atomic(path, content):
    path=Path(path)
    check_local(path)
    tmp=path.with_name('.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('xb') as out:
            out.write(content); out.flush(); os.fsync(out.fileno())
        check_local(path)
        os.replace(tmp,path)
    finally:
        if tmp.exists():
            check_local(tmp)
            tmp.unlink()

class Application:
    def __init__(self, root):
        self.root=check_local(root)
        self.root.mkdir(parents=True,exist_ok=True)
        self.store=Store(self.root/'records')
        self.lock=threading.RLock()
        self.uploads={}
        self.downloads={}
        self.model=LocalModel()
        self.docroot=self.root/'documents'
        check_local(self.docroot)
        self.docroot.mkdir(exist_ok=True)
        self.exports=self.root/'exports'
        check_local(self.exports)
        self.exports.mkdir(exist_ok=True)
        self.docindex=self.docroot/'index.json'
        check_local(self.docindex)
        self.documents=json.loads(read_limited(self.docindex)) if self.docindex.exists() else []
        if not isinstance(self.documents,list) or len(self.documents)>10000: raise ValueError('Document index is invalid.')
        seen=set()
        for d in self.documents:
            if not isinstance(d,dict) or not re.fullmatch('[a-f0-9]{32}',d.get('id','')) or d['id'] in seen or not re.fullmatch(r'[a-f0-9]{32}\.[a-z0-9]{1,10}',d.get('storage','')) or not re.fullmatch('[a-f0-9]{64}',d.get('hash','')):
                raise ValueError('Document index is invalid.')
            safe_name(d.get('name')); seen.add(d['id'])
        self.settings={'privacy_acknowledged':False}
        settings=self.root/'settings.json'
        check_local(settings)
        if settings.exists():
            value=json.loads(read_limited(settings,10000))
            if not isinstance(value,dict) or set(value)!={'privacy_acknowledged'} or type(value['privacy_acknowledged']) is not bool:
                raise ValueError('Settings could not be read safely.')
            self.settings.update(value)

    def snapshot(self):
        with self.lock,self.store._lock:
            state=self.store.state()
            state['setup']['privacy_acknowledged']=self.settings.get('privacy_acknowledged',False)
            return {'state':state,'overview':self.store.overview(),'proposals':self.store.pending(),
                'documents':[{k:v for k,v in d.items() if k not in ('hash','storage')} for d in self.documents],
                'settings':self.settings,'version':VERSION,'data_dir':str(self.root),'model':self.model.status()}

    def get_doc(self, identifier):
        found=next((d for d in self.documents if d['id']==identifier),None)
        if not found: raise ValueError('Choose an imported document.')
        if not re.fullmatch(r'[a-f0-9]{32}\.[a-z0-9]{1,10}',found['storage']): raise ValueError('Invalid document reference.')
        p=self.docroot/found['storage']
        content=read_limited(p)
        if hashlib.sha256(content).hexdigest()!=found['hash']: raise ValueError('Imported original has changed. Preserve it and import a new version.')
        return found,content

    def preview(self,name,content):
        safe_name(name)
        if len(content)>10_000_000: raise ValueError('File exceeds the 10 MB import limit.')
        result=preview_file(name,content)
        identifier=uuid.uuid4().hex
        with self.lock:
            if len(self.uploads)>=20:
                # Only ephemeral, unapproved file previews are released; no records/drafts change.
                self.uploads.pop(next(iter(self.uploads)))
            self.uploads[identifier]={'content':content,'preview':result}
        result=dict(result,id=identifier)
        result['entries']=result.get('members',[])
        digest=hashlib.sha256(content).hexdigest()
        result['duplicate']=any(d['hash']==digest for d in self.documents)
        return result

    def route(self,path,data):
        if not isinstance(data,dict): raise ValueError('Expected a request object.')
        if path=='/api/propose':
            kind=data.get('kind'); values=data.get('data')
            if kind=='setup' and isinstance(values,dict):
                values=dict(values); values.pop('privacy_acknowledged',None)
            return self.store.propose(kind,values)
        if path=='/api/approve':
            if type(data.get('revision')) is not int: raise ValueError('Review the current proposal before approval.')
            before=next((p for p in self.store.pending() if p['id']==data.get('id')),None)
            result=self.store.approve(data.get('id'),data['revision'],allow_duplicates=data.get('allow_duplicates') is True)
            if before and before['kind']=='setup':
                self.settings['privacy_acknowledged']=True
                try: write_atomic(self.root/'settings.json',json_bytes(self.settings))
                except OSError:
                    result['notice']='Your financial setup was saved. The onboarding preference could not be saved, so the introduction may appear again.'
            return result
        if path=='/api/reject': return self.store.reject(data.get('id'))
        if path=='/api/demo': return self.store.demo()
        if path=='/api/upload':
            try: content=base64.b64decode(data.get('base64',''),validate=True)
            except (ValueError,TypeError): raise ValueError('File data could not be read.') from None
            return self.preview(data.get('name'),content)
        if path=='/api/zip-member':
            upload=self.uploads.get(data.get('id'))
            if not upload or upload['preview'].get('status')!='archive': raise ValueError('Preview a valid archive first.')
            member=data.get('member')
            found=next((m for m in upload['preview'].get('members',[]) if m['name']==member),None)
            if not found or found.get('status')=='rejected': raise ValueError('Choose a safe archive member.')
            with zipfile.ZipFile(io.BytesIO(upload['content'])) as archive:
                content=archive.read(member)
            result=self.preview(Path(member).name,content)
            result['archive_source']=upload['preview']['name']+' / '+member
            return result
        if path=='/api/document-preview':
            doc,content=self.get_doc(data.get('id'))
            return self.preview(doc['name'],content)
        if path=='/api/import':
            with self.lock:
                uploaded=self.uploads.get(data.get('id'))
                if not uploaded: raise ValueError('Preview the file again before importing it.')
                p=uploaded['preview']
                if p['status']=='rejected': raise ValueError('This file was rejected and cannot be imported.')
                digest=hashlib.sha256(uploaded['content']).hexdigest()
                existing=next((d for d in self.documents if d['hash']==digest),None)
                if existing: return dict(existing,duplicate=True,message='An identical original is already in the library; no second copy was saved.')
                if len(self.documents)>=10000: raise ValueError('The document library limit has been reached.')
                ident=uuid.uuid4().hex
                suffix=Path(p['name']).suffix.lower().lstrip('.')
                suffix=suffix if re.fullmatch('[a-z0-9]{1,10}',suffix) else 'bin'
                storage=ident+'.'+suffix
                version=1+sum(d['name']==p['name'] for d in self.documents)
                doc={'id':ident,'name':p['name'],'status':p['status'],'version':version,'storage':storage,'hash':digest,
                     'imported_at':datetime.now(timezone.utc).isoformat(),'warnings':p.get('warnings',[])}
                check_local(self.docroot/storage)
                with (self.docroot/storage).open('xb') as out: out.write(uploaded['content'])
                updated=self.documents+[doc]
                write_atomic(self.docindex,json_bytes(updated))
                self.documents=updated
                return {k:v for k,v in doc.items() if k not in ('hash','storage')}
        if path=='/api/import-propose':
            upload=self.uploads.get(data.get('id'))
            if upload: preview=upload['preview']
            else:
                doc,content=self.get_doc(data.get('id'))
                preview=preview_file(doc['name'],content)
            rows=preview.get('rows',[])
            if not rows: raise ValueError('This file has no canonical transaction rows. Use the notes field or the manual entry form.')
            allowed={'date','description','amount','account','classification','category','source'}
            warnings=list(preview.get('warnings',[]))
            if any(r.get('warnings') for r in rows): warnings.append('Some source rows contain formula or parsing warnings. Compare every value with the source before approval.')
            with self.store._lock:
                proposal=self.store.propose('transactions',[{k:r.get(k,'') for k in allowed} for r in rows])
                try: return self.store.annotate(proposal['id'],warnings[:100],[])
                except Exception:
                    self.store.reject(proposal['id'])
                    raise
        if path=='/api/model/start': return self.model.start(data.get('executable',''),data.get('model',''))
        if path=='/api/analyze':
            text=data.get('text','')
            if not isinstance(text,str): raise ValueError('Enter text notes.')
            text='NOTES (entered locally):\n'+text
            identifiers=data.get('document_ids',[])
            if not isinstance(identifiers,list) or len(identifiers)>5: raise ValueError('Select at most five documents at a time.')
            for ident in identifiers:
                doc,content=self.get_doc(ident)
                preview=preview_file(doc['name'],content)
                if preview['status'] not in ('ready','preview_only') or not preview.get('text'):
                    raise ValueError('A selected document cannot supply text. Use a supported file or enter notes manually.')
                text+='\nSOURCE: '+doc['name']+'\n'+preview['text']
            response=self.model.analyze(text,data.get('model',''))
            rows=response.pop('transactions')
            # A draft must not be observable/approvable until all review context exists.
            with self.store._lock:
                response['proposal']=self.store.propose('transactions',rows) if rows else None
                if response['proposal']:
                    ident=response['proposal']['id']
                    try: response['proposal']=self.store.annotate(ident,response['warnings'],response['questions'])
                    except Exception:
                        self.store.reject(ident)
                        raise
            return response
        if path=='/api/export': return self.export(data.get('format'))
        raise ValueError('This action is not supported.')

    def export(self,kind):
        with self.lock,self.store._lock:
            state=self.store.export_state(); overview=self.store.overview()
            if kind=='xlsx': content=xlsx_bytes(state,overview); ext='xlsx'
            elif kind=='csv': content=csv_bytes(state['transactions']); ext='csv'
            elif kind=='html': content=report_html(state,overview).encode('utf-8'); ext='html'
            elif kind=='json': content=json_bytes(state); ext='json'
            elif kind=='backup':
                out=io.BytesIO()
                total=0; count=0
                with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
                    # Explicit storage-only allowlist; no session token or model data.
                    for folder in ('records','documents'):
                        for p in owned_files(self.root/folder):
                            count+=1
                            if count>MAX_BACKUP_FILES: raise ValueError('The backup contains too many files. Preserve this data folder and copy it locally while the app is closed.')
                            remaining=MAX_BACKUP_BYTES-total
                            content=read_limited(p,min(32*1024*1024,remaining))
                            total+=len(content)
                            z.writestr(p.relative_to(self.root).as_posix(),content)
                            if out.tell()>MAX_BACKUP_BYTES: raise ValueError('The backup exceeds the supported size. Copy the data folder locally while the app is closed.')
                    z.writestr('settings.json',json_bytes(self.settings))
                    z.writestr('BACKUP-INFO.json',json_bytes({'format':'private-accounting-personal','version':1,'created':datetime.now(timezone.utc).isoformat()}))
                content=out.getvalue(); ext='zip'
            else: raise ValueError('Choose XLSX, CSV, printable HTML, JSON or backup.')
            filename='Personal-Finance-'+('Backup-' if kind=='backup' else '')+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.'+ext
            check_local(self.exports/filename)
            with (self.exports/filename).open('xb') as stream: stream.write(content)
            identifier=uuid.uuid4().hex
            if len(self.downloads)>=MAX_DOWNLOADS: self.downloads.pop(next(iter(self.downloads)))
            self.downloads[identifier]=(filename,self.exports/filename)
            return {'filename':filename,'url':'/api/download/'+identifier,'path':str(self.exports/filename)}


class RequestReader(io.RawIOBase):
    """Buffered HTTP input with cancellable waits, including on Windows sockets."""
    def __init__(self,connection,closing):
        self.connection=connection; self.closing=closing
        self.timeout=connection.gettimeout()

    def readable(self): return True

    def readinto(self,buffer):
        if not buffer: return 0
        deadline=time.monotonic()+self.timeout
        while not self.closing.is_set():
            remaining=deadline-time.monotonic()
            if remaining<=0: raise TimeoutError('Local request read timed out.')
            if select.select([self.connection],[],[],min(.1,remaining))[0]:
                return self.connection.recv_into(buffer)
        return 0


class BoundedHTTPServer(ThreadingHTTPServer):
    """Bound workers before threads are created, including idle HTTP connections."""
    daemon_threads=False

    def __init__(self,*args,**kwargs):
        self._slots=threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._connections=set()
        self._connection_lock=threading.Lock()
        self._closing=threading.Event()
        super().__init__(*args,**kwargs)

    def process_request(self,request,client_address):
        request.settimeout(SOCKET_TIMEOUT)
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        with self._connection_lock: self._connections.add(request)
        try: super().process_request(request,client_address)
        except BaseException:
            with self._connection_lock: self._connections.discard(request)
            self._slots.release()
            raise

    def process_request_thread(self,request,client_address):
        try: super().process_request_thread(request,client_address)
        finally:
            with self._connection_lock: self._connections.discard(request)
            self._slots.release()

    def server_close(self):
        # Interrupt idle reads, then let active mutations finish before releasing
        # the launcher's data-folder lock. No worker may outlive that ownership.
        self._closing.set()
        with self._connection_lock: connections=list(self._connections)
        for connection in connections:
            try: connection.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        super().server_close()

    def handle_error(self,request,client_address):
        # Disconnected/malformed clients must not dump request details to stderr.
        pass


def make_server(app,port=0,token=None):
    token=token or secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        server_version='PrivateAccounting'
        sys_version=''
        def setup(self):
            super().setup()
            self.rfile.close()
            self.rfile=io.BufferedReader(RequestReader(self.connection,self.server._closing))
        def log_message(self,*args): pass
        def common(self,content_type,length):
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(length))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")
        def reply(self,status,data):
            content=json_bytes(data)
            self.send_response(status); self.common('application/json; charset=utf-8',len(content)); self.end_headers()
            self.wfile.write(content)
        def boundary(self,auth=False):
            expected=f'127.0.0.1:{self.server.server_port}'
            if any(len(self.headers.get_all(h,[]))>1 for h in ('Host','Origin','Sec-Fetch-Site','Authorization')) or self.headers.get('Host')!=expected or self.headers.get('Origin') not in (None,'http://'+expected) or self.headers.get('Sec-Fetch-Site')=='cross-site':
                self.reply(403,{'error':'Only the local application origin is allowed.'}); return False
            if auth and not secrets.compare_digest(self.headers.get('Authorization','').encode('utf-8'),('Bearer '+token).encode('utf-8')):
                self.reply(401,{'error':'Open the application through its launcher to establish a local session.'}); return False
            return True
        def do_OPTIONS(self): self.reply(403,{'error':'Cross-origin access is not permitted.'})
        def do_GET(self):
            if not self.boundary(self.path.startswith('/api/')): return
            try:
                if self.path=='/api/ping': return self.reply(200,{'ok':True,'version':VERSION})
                if self.path=='/api/state': return self.reply(200,app.snapshot())
                if self.path=='/api/model/status': return self.reply(200,app.model.status())
                if self.path.startswith('/api/download/'):
                    saved=app.downloads.get(self.path.rsplit('/',1)[-1])
                    if not saved: return self.reply(404,{'error':'Export not found in this session.'})
                    name,p=saved; content=read_limited(p,256*1024*1024)
                    self.send_response(200); self.common('application/octet-stream',len(content))
                    self.send_header('Content-Disposition','attachment; filename="'+name+'"'); self.end_headers(); self.wfile.write(content); return
                files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/styles.css':('styles.css','text/css; charset=utf-8')}
                if self.path in files:
                    name,mime=files[self.path]; content=(STATIC/name).read_bytes()
                    self.send_response(200); self.common(mime,len(content)); self.end_headers(); self.wfile.write(content); return
                self.reply(404,{'error':'Not found.'})
            except (OSError,ValueError,FinanceError): self.reply(400,{'error':'Saved data could not be read. Preserve this data folder and check the troubleshooting guide.'})
        def do_POST(self):
            if not self.boundary(True): return
            try:
                if self.headers.get('Transfer-Encoding') is not None or len(self.headers.get_all('Content-Length',[]))!=1:
                    return self.reply(400,{'error':'Use one explicit request length without transfer encoding.'})
                if self.headers.get('Content-Type','').split(';')[0]!='application/json': return self.reply(415,{'error':'JSON requests only.'})
                length=int(self.headers.get('Content-Length','0'))
                if length<1 or length>MAX_BODY: return self.reply(413,{'error':'Request is empty or exceeds the file size limit.'})
                body=self.rfile.read(length)
                if len(body)!=length: raise ValueError('The request was incomplete. Nothing was saved.')
                data=json.loads(body)
                if self.path=='/api/shutdown':
                    if not isinstance(data,dict) or data.get('confirm') is not True: raise ValueError('Confirm closing this application.')
                    self.reply(200,{'closed':True})
                    threading.Thread(target=self.server.shutdown,daemon=True).start(); return
                self.reply(200,app.route(self.path,data))
            except (ValueError,FinanceError,ModelError) as exc:
                # Validation errors contain application-defined text, not record dumps.
                self.reply(400,{'error':str(exc)[:500]})
            except (OSError,zipfile.BadZipFile,KeyError,TypeError): self.reply(400,{'error':'The action could not be completed safely. Your approved records were preserved.'})
            except Exception: self.reply(500,{'error':'An internal error occurred. Your files were preserved; consult Troubleshooting.'})
    server=BoundedHTTPServer(('127.0.0.1',port),Handler)
    server.token=token
    return server
