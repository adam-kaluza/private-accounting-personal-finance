"""Create (do not open) an offline Sandbox configuration for this edition."""
from pathlib import Path
from xml.sax.saxutils import escape
import ctypes
import os
import stat

def _local(path):
    path=Path(os.path.abspath(path))
    if str(path).startswith(('\\\\','//')):raise ValueError('Use a local application folder.')
    for part in (path,*path.parents):
        try:info=part.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400 or (stat.S_ISREG(info.st_mode) and info.st_nlink>1):
            raise ValueError('Linked or redirected paths cannot be mapped into Sandbox.')
    return path

def create_configuration(root):
    root=_local(root)
    data=_local(root/'data')
    data.mkdir(exist_ok=True)
    config=_local(root/'Private Accounting Offline.wsb')
    content=f'''<Configuration>
  <Networking>Disable</Networking>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <PrinterRedirection>Disable</PrinterRedirection>
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <vGPU>Disable</vGPU>
  <MappedFolders>
    <MappedFolder><HostFolder>{escape(str(root))}</HostFolder><SandboxFolder>C:\\PrivateFinance</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>{escape(str(data))}</HostFolder><SandboxFolder>C:\\FinanceData</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand><Command>C:\\PrivateFinance\\runtime\\pythonw.exe C:\\PrivateFinance\\app\\launch.py --data-dir C:\\FinanceData</Command></LogonCommand>
</Configuration>
'''
    try:
        with config.open('x',encoding='utf-8') as out:out.write(content)
        return {'created':True,'path':str(config)}
    except FileExistsError:
        return {'created':False,'path':str(config)}

if __name__=='__main__':
    try:
        result=create_configuration(Path(__file__).absolute().parents[1])
        message=('Created Private Accounting Offline.wsb beside the launcher.' if result['created'] else 'The existing offline Sandbox configuration was preserved.')+' Read it, then open it yourself only when no other Sandbox is running. No existing app or Sandbox was changed.'
    except (ValueError,OSError):
        message='Could not create the offline configuration safely. Use an ordinary local folder without links and check write permissions. No Sandbox was opened or changed.'
    ctypes.windll.user32.MessageBoxW(0,message,'Private Accounting',0x40)
