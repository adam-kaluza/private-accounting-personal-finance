"""Windows installer regression tests. Every archive and store is fictional."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'installer'/'install.ps1'
POWERSHELL=shutil.which('powershell.exe')

def quote(value):return "'"+str(value).replace("'","''")+"'"

@unittest.skipUnless(os.name=='nt' and POWERSHELL,'Windows PowerShell installer')
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='.ins-')
        self.root=Path(self.tmp.name)
        self.assertTrue(self.root.resolve().is_relative_to((ROOT/'tests').resolve()))
        self.home=self.root/'home'
        self.archive=self.make_zip()
        self.script=self.make_script(self.archive)

    def tearDown(self):self.tmp.cleanup()

    def make_zip(self,name='fictional.zip',extras=(),omit=()):
        target=self.root/name
        files={
            'PrivateAccounting/app/launch.py':b'# fictional launcher; never executed\n',
            'PrivateAccounting/app/server.py':b'# fictional server; never executed\n',
            'PrivateAccounting/runtime/pythonw.exe':b'fictional executable marker; never executed',
            'PrivateAccounting/README.md':b'Fictional installer fixture only.\n',
            'PrivateAccounting/LICENSE':b'Fictional fixture license marker.\n',
            'PrivateAccounting/examples/fictional.txt':b'Fictional grocery receipt -4.50\n',
        }
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
            for path,content in files.items():
                if path not in omit:z.writestr(path,content)
            for path,content in extras:
                if isinstance(path,str):
                    # ZipInfo normalizes backslashes on Windows at construction.
                    # Assign after construction to retain truly malformed bytes.
                    info=zipfile.ZipInfo('fixture');info.filename=path;info.orig_filename=path;info.compress_type=zipfile.ZIP_DEFLATED
                else:info=path
                z.writestr(info,content)
        return target

    def make_script(self,archive,version='1.1.0',digest=None):
        digest=digest or hashlib.sha256(archive.read_bytes()).hexdigest()
        text=SCRIPT.read_text('utf-8')
        text,n=re.subn(r"(?m)^\$ArchiveSha256 = '[^']*'$","$ArchiveSha256 = '"+digest+"'",text)
        self.assertEqual(n,1)
        text,n=re.subn(r"(?m)^\$ReleaseVersion = '[^']*'$","$ReleaseVersion = '"+version+"'",text)
        self.assertEqual(n,1)
        target=self.root/('installer-'+version+'.ps1')
        target.write_text(text,encoding='utf-8-sig')
        return target

    def run_ps(self,code,ok=True):
        completed=subprocess.run([POWERSHELL,'-NoLogo','-NoProfile','-NonInteractive','-Command',code],capture_output=True,text=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if ok:self.assertEqual(completed.returncode,0,completed.stderr[-2000:]+completed.stdout[-2000:])
        else:self.assertNotEqual(completed.returncode,0,'Unexpected installer success: '+completed.stdout[-1000:])
        return completed

    def install(self,archive=None,script=None,home=None,extra='',ok=True):
        command='& ([scriptblock]::Create([IO.File]::ReadAllText('+quote(script or self.script)+'))) -ArchivePath '+quote(archive or self.archive)+' -InstallRoot '+quote(home or self.home)+' '+extra+' | ConvertTo-Json -Depth 6 -Compress'
        result=self.run_ps(command,ok)
        return json.loads(result.stdout.strip()) if ok else result

    def assert_no_stage(self,home=None):
        home=home or self.home
        if home.exists():self.assertEqual(list(home.glob('.install-*')),[])

    def test_fresh_install_is_separate_and_non_launching(self):
        before=self.archive.read_bytes()
        result=self.install()
        self.assertEqual(result['status'],'installed')
        self.assertTrue(result['archive_verified'])
        self.assertFalse(result['launch_requested'])
        self.assertEqual(result['shortcut'],'not-requested')
        self.assertEqual(Path(result['data_dir']),self.home/'data')
        self.assertEqual(list((self.home/'data').iterdir()),[])
        self.assertEqual((self.home/'versions'/'1.1.0'/'README.md').read_text(),'Fictional installer fixture only.\n')
        launcher=Path(result['launcher']).read_text()
        self.assertIn('DisableDelayedExpansion',launcher)
        self.assertIn('--data-dir "%~dp0data"',launcher)
        self.assertEqual(self.archive.read_bytes(),before)
        self.assert_no_stage()

    def test_repeat_install_verifies_and_preserves_data(self):
        first=self.install()
        marker=self.home/'data'/'fictional-record.txt';marker.write_text('fictional saved record')
        launcher=Path(first['launcher']);original=launcher.read_bytes()
        result=self.install()
        self.assertEqual(result['status'],'already-installed')
        self.assertEqual(marker.read_text(),'fictional saved record')
        self.assertEqual(launcher.read_bytes(),original)
        self.assert_no_stage()

    def test_second_version_preserves_first_and_persistent_data(self):
        self.install()
        marker=self.home/'data'/'fictional-record.txt';marker.write_text('fictional record')
        old=self.home/'versions'/'1.1.0'/'README.md';before=old.read_bytes()
        second=self.make_script(self.archive,version='1.1.1')
        result=self.install(script=second)
        self.assertEqual(result['status'],'installed')
        self.assertEqual(old.read_bytes(),before)
        self.assertTrue((self.home/'versions'/'1.1.1'/'README.md').is_file())
        self.assertEqual(marker.read_text(),'fictional record')
        self.assertTrue((self.home/'Start Personal Finance 1.1.0.cmd').is_file())

    def test_bad_hash_never_extracts(self):
        script=self.make_script(self.archive,digest='0'*64)
        result=self.install(script=script,ok=False)
        self.assertIn('checksum',result.stderr.lower())
        self.assertFalse((self.home/'versions').exists())
        self.assertFalse((self.home/'data').exists())
        self.assert_no_stage()

    def test_incomplete_archive_never_extracts(self):
        truncated=self.root/'truncated.zip';truncated.write_bytes(self.archive.read_bytes()[:80])
        self.install(archive=truncated,ok=False)
        self.assertFalse((self.home/'versions').exists())
        self.assert_no_stage()

    def test_non_zip_with_matching_hash_is_refused(self):
        bad=self.root/'not-a-zip.bin';bad.write_bytes(b'fictional non archive')
        self.install(archive=bad,script=self.make_script(bad),ok=False)
        self.assertFalse((self.home/'versions').exists())
        self.assert_no_stage()

    def test_missing_component_is_refused(self):
        bad=self.make_zip('missing.zip',omit=('PrivateAccounting/runtime/pythonw.exe',))
        self.install(archive=bad,script=self.make_script(bad),ok=False)
        self.assertFalse((self.home/'versions').exists())
        self.assert_no_stage()

    def test_directory_cannot_satisfy_required_component(self):
        bad=self.make_zip('directory-component.zip',extras=(('PrivateAccounting/runtime/pythonw.exe/',b''),),omit=('PrivateAccounting/runtime/pythonw.exe',))
        self.install(archive=bad,script=self.make_script(bad),ok=False)
        self.assertFalse((self.home/'versions').exists());self.assert_no_stage()

    def test_archive_traversal_and_root_escape_are_refused(self):
        for index,path in enumerate(('PrivateAccounting/../escaped.txt','/absolute.txt','OtherApp/file.txt','PrivateAccounting/app/../../escaped.txt')):
            with self.subTest(path=path):
                bad=self.make_zip('unsafe'+str(index)+'.zip',extras=((path,b'fictional'),))
                home=self.root/('bad'+str(index))
                self.install(archive=bad,script=self.make_script(bad),home=home,ok=False)
                self.assertFalse((home/'versions').exists());self.assert_no_stage(home)
        self.assertFalse((self.root/'escaped.txt').exists())

    def test_windows_ambiguous_archive_names_are_refused(self):
        paths=('PrivateAccounting/app/file.txt:secret','PrivateAccounting/app/NUL.txt','PrivateAccounting/app/trailing.','PrivateAccounting/app\\escape.txt','PrivateAccounting/APP/LAUNCH.PY')
        for index,path in enumerate(paths):
            with self.subTest(path=path):
                bad=self.make_zip('ambiguous'+str(index)+'.zip',extras=((path,b'fictional'),))
                home=self.root/('bad'+str(index))
                self.install(archive=bad,script=self.make_script(bad),home=home,ok=False)
                self.assertFalse((home/'versions').exists());self.assert_no_stage(home)

    def test_archive_data_and_links_are_refused(self):
        linked=zipfile.ZipInfo('PrivateAccounting/app/link');linked.create_system=3;linked.external_attr=(0o120777<<16)
        for index,extra in enumerate(((('PrivateAccounting/data/fictional.txt',b'fictional'),),((linked,b'fictional-target'),))):
            bad=self.make_zip('blocked'+str(index)+'.zip',extras=extra)
            home=self.root/('bad'+str(index))
            self.install(archive=bad,script=self.make_script(bad),home=home,ok=False)
            self.assertFalse((home/'versions').exists());self.assert_no_stage(home)

    def test_archive_expansion_ratio_is_bounded(self):
        bad=self.make_zip('compressed.zip',extras=(('PrivateAccounting/large.txt',b'x'*200000),))
        self.install(archive=bad,script=self.make_script(bad),ok=False)
        self.assertFalse((self.home/'versions').exists());self.assert_no_stage()

    def test_unowned_nonempty_destination_is_preserved(self):
        self.home.mkdir();marker=self.home/'fictional-original.txt';marker.write_text('fictional original')
        self.install(ok=False)
        self.assertEqual(marker.read_text(),'fictional original')
        self.assertEqual({p.name for p in self.home.iterdir()},{marker.name})

    def test_altered_installed_file_is_preserved_and_refused(self):
        self.install()
        changed=self.home/'versions'/'1.1.0'/'README.md';changed.write_text('fictional user edit')
        self.install(ok=False)
        self.assertEqual(changed.read_text(),'fictional user edit');self.assert_no_stage()

    def test_existing_launcher_collision_is_preserved(self):
        result=self.install();launcher=Path(result['launcher']);launcher.write_text('fictional custom launcher')
        self.install(ok=False)
        self.assertEqual(launcher.read_text(),'fictional custom launcher');self.assert_no_stage()

    def test_unowned_version_collision_is_preserved(self):
        self.install()
        target=self.home/'versions'/'1.1.1';target.mkdir();marker=target/'fictional-original.txt';marker.write_text('fictional original')
        self.install(script=self.make_script(self.archive,version='1.1.1'),ok=False)
        self.assertEqual(marker.read_text(),'fictional original');self.assert_no_stage()

    def test_incomplete_download_cleanup_preserves_existing_data(self):
        self.install()
        marker=self.home/'data'/'fictional-record.txt';marker.write_text('fictional saved')
        command='. ([scriptblock]::Create([IO.File]::ReadAllText('+quote(self.script)+'))) -FunctionsOnly; function Receive-ReleaseArchive { param($Uri,$Destination) [IO.File]::WriteAllText($Destination,"fictional partial download"); throw "Fictional transport interrupted" }; try { Invoke-PersonalFinanceInstall -Root '+quote(self.home)+' -Version "1.1.1" -ExpectedHash '+quote(hashlib.sha256(self.archive.read_bytes()).hexdigest())+' -Url "https://github.com/fictional/fixture/releases/download/v1.1.1/fixture.zip"; exit 9 } catch { if($_.Exception.Message -notmatch "Fictional transport interrupted"){throw}; Write-Output "EXPECTED_INTERRUPTION" }'
        result=self.run_ps(command)
        self.assertIn('EXPECTED_INTERRUPTION',result.stdout)
        self.assertEqual(marker.read_text(),'fictional saved')
        self.assertFalse((self.home/'versions'/'1.1.1').exists());self.assert_no_stage()

    def test_network_share_and_overlong_data_path_are_refused(self):
        self.install(home=r'\\fictional.invalid\share\app',ok=False)
        long=self.root/('l'*max(1,156-len(str(self.root))))
        self.install(home=long,ok=False)
        self.assertFalse(long.exists())

    def test_mapped_network_drive_is_refused_without_accessing_network(self):
        command='. ([scriptblock]::Create([IO.File]::ReadAllText('+quote(self.script)+'))) -FunctionsOnly; function Get-InstallerDriveType { param($Path) return [IO.DriveType]::Network }; try { Invoke-PersonalFinanceInstall -Root '+quote(self.home)+' -Archive '+quote(self.archive)+' -Version "1.1.0" -ExpectedHash '+quote(hashlib.sha256(self.archive.read_bytes()).hexdigest())+'; exit 9 } catch { if($_.Exception.Message -notmatch "mapped network drives are refused"){throw}; Write-Output "EXPECTED_NETWORK_REFUSAL" }'
        result=self.run_ps(command)
        self.assertIn('EXPECTED_NETWORK_REFUSAL',result.stdout)
        self.assertFalse(self.home.exists())

    def test_transient_directory_lock_retries_without_overwriting(self):
        source=self.root/'fictional-stage';source.mkdir();(source/'marker.txt').write_text('fictional marker')
        target=self.root/'fictional-installed'
        command='. ([scriptblock]::Create([IO.File]::ReadAllText('+quote(self.script)+'))) -FunctionsOnly; Initialize-InstallerTypes; $script:attempts=0; function Move-VersionDirectory { param($Source,$Target) $script:attempts++; if($script:attempts -lt 3){throw [IO.IOException]::new("Fictional scanner lock")}; [IO.Directory]::Move($Source,$Target) }; Commit-VersionDirectory '+quote(source)+' '+quote(target)+'; if($script:attempts -ne 3){throw "Retry count differs"}; Write-Output "RETRY_PASSED"'
        result=self.run_ps(command)
        self.assertIn('RETRY_PASSED',result.stdout)
        self.assertFalse(source.exists())
        self.assertEqual((target/'marker.txt').read_text(),'fictional marker')

    def test_shortcut_is_opt_in_and_existing_name_preserved(self):
        desktop=self.root/'fictional-desktop';desktop.mkdir()
        result=self.install(extra='-DesktopShortcut -ShortcutDirectory '+quote(desktop))
        self.assertEqual(result['shortcut'],'created')
        link=desktop/'Private Accounting Personal Finance 1.1.0.lnk'
        self.assertTrue(link.is_file());original=link.read_bytes()
        result=self.install(extra='-DesktopShortcut -ShortcutDirectory '+quote(desktop))
        self.assertEqual(result['shortcut'],'existing-name-preserved')
        self.assertEqual(link.read_bytes(),original)

    def test_punctuation_in_install_path_is_supported(self):
        result=self.install(home=self.root/"fictional & it's !local!")
        self.assertEqual(result['status'],'installed')
        self.assertIn('DisableDelayedExpansion',Path(result['launcher']).read_text())

    def test_hardlinked_control_file_is_refused(self):
        self.install()
        original=self.root/'fictional-original.txt';original.write_text('fictional original')
        launcher=self.home/'Start Personal Finance 1.1.0.cmd';launcher.unlink()
        try:os.link(original,launcher)
        except OSError as exc:self.skipTest('This environment cannot create a hardlink: '+str(exc.errno))
        self.install(ok=False)
        self.assertEqual(original.read_text(),'fictional original')

    def test_junction_destination_is_refused(self):
        target=self.root/'fictional-target';target.mkdir()
        link=self.root/'fictional-junction'
        self.assertTrue(target.resolve().is_relative_to(self.root.resolve()))
        self.assertTrue(link.parent.resolve().is_relative_to(self.root.resolve()))
        result=subprocess.run([POWERSHELL,'-NoProfile','-NonInteractive','-Command',"$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path "+quote(link)+' -Target '+quote(target)+' | Out-Null'],capture_output=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:self.skipTest('This environment cannot create a junction.')
        try:
            self.install(home=link,ok=False)
            self.assertEqual(list(target.iterdir()),[])
        finally:os.rmdir(link)

    def test_no_policy_or_privileged_system_changes_in_installer(self):
        source=SCRIPT.read_text('utf-8')
        for operation in ('Set-ExecutionPolicy','-ExecutionPolicy Bypass','RunAs','Stop-Process','Restart-Computer','Invoke-Expression','Enable-WindowsOptionalFeature'):
            self.assertNotIn(operation,source)

if __name__=='__main__':unittest.main()
