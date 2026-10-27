"""Portable launcher. It creates only this edition's own explicitly selected data."""
from __future__ import annotations
import argparse
import atexit
import ctypes
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import webbrowser

sys.path.insert(0,str(Path(__file__).parent))
from server import Application, make_server, json_bytes, write_atomic, check_local, read_limited

def outbound_guard(event,args):
    if event=='socket.connect':
        address=args[1]
        if not isinstance(address,tuple) or address[0]!='127.0.0.1':
            raise PermissionError('This application permits loopback connections only.')
    if event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1',b'127.0.0.1'):
        raise PermissionError('External name resolution is disabled.')

def open_window(url,root):
    check_local(root/'browser-profile')
    candidates=[Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',
                Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Microsoft/Edge/Application/msedge.exe']
    edge=next((p for p in candidates if p.is_file()),None)
    if edge:
        subprocess.Popen([str(edge),'--app='+url,'--user-data-dir='+str(root/'browser-profile'),
            '--no-first-run','--disable-sync','--disable-extensions','--disable-background-networking'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    else:
        webbrowser.open(url)

def acquire_lock(root):
    root=check_local(root)
    root.mkdir(parents=True,exist_ok=True)
    check_local(root/'.app.lock')
    stream=(root/'.app.lock').open('a+b')
    if stream.tell()==0: stream.write(b'0'); stream.flush()
    stream.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return stream
    except OSError:
        stream.close(); return None

def main():
    parser=argparse.ArgumentParser(description='Private Accounting — Personal finance')
    parser.add_argument('--data-dir',type=Path,default=Path(__file__).resolve().parents[1]/'data')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args()
    root=check_local(args.data_dir)
    if os.name=='nt' and len(str(root))>155:
        message='The extraction path is too long for reliable Windows storage. Move this whole application folder to a shorter local path, then launch it again. All existing files are preserved.'
        if not args.no_browser: ctypes.windll.user32.MessageBoxW(0,message,'Private Accounting',0x30)
        else: print(message,file=sys.stderr)
        return 1
    sys.addaudithook(outbound_guard)
    lock=acquire_lock(root)
    session=root/'session.json'
    if lock is None:
        # Check only the process control endpoint, never financial records.
        try:
            info=json.loads(read_limited(session,10000))
            if not isinstance(info,dict) or type(info.get('port')) is not int or not 1<=info['port']<=65535 or not isinstance(info.get('token'),str) or len(info['token'])>200:
                raise ValueError()
            conn=http.client.HTTPConnection('127.0.0.1',int(info['port']),timeout=2)
            conn.request('GET','/api/ping',headers={'Authorization':'Bearer '+info['token']})
            response=conn.getresponse(); good=response.status==200; response.read(); conn.close()
            if not good: raise ValueError()
            if not args.no_browser: open_window(f"http://127.0.0.1:{info['port']}/#{info['token']}",root)
            return 0
        except Exception:
            raise ValueError('This data folder is already in use. Leave its files in place; close the application normally before reopening.') from None
    app=None; server=None; owns_session=False
    try:
        app=Application(root)
        server=make_server(app,args.port)
        url=f'http://127.0.0.1:{server.server_port}/#{server.token}'
        write_atomic(session,json_bytes({'port':server.server_port,'token':server.token,'pid':os.getpid()}))
        owns_session=True
        if not args.no_browser: open_window(url,root)
        server.serve_forever(poll_interval=.2)
    finally:
        try:
            try:
                if app is not None: app.model.close()
            finally:
                if server is not None: server.server_close()
        finally:
            try:
                if owns_session and session.exists():
                    check_local(session)
                    session.unlink()
            finally:
                lock.close()
    return 0

if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception:
        message='Private Accounting could not start. Preserve the data folder. Check that the ZIP is fully extracted to a writable local folder and read docs/TROUBLESHOOTING.md. No existing application was stopped.'
        if os.name=='nt' and not sys.stderr:
            ctypes.windll.user32.MessageBoxW(0,message,'Private Accounting',0x10)
        else: print(message,file=sys.stderr)
        raise SystemExit(1)
