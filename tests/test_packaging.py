"""Packaging/configuration checks using only release files and fictional fixtures."""
from pathlib import Path
import hashlib
import importlib.util
import os
import subprocess
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]

def module(name,rel):
    spec=importlib.util.spec_from_file_location(name,ROOT/rel)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

build=module('release_builder','tools/build_release.py')
sandbox=module('sandbox_config','tools/create_sandbox.py')

class PackagingTests(unittest.TestCase):
    def test_dependencies_match_published_pins(self):
        for name,digest in ((build.PYTHON_ARCHIVE,build.PYTHON_SHA),(build.PYPDF_ARCHIVE,build.PYPDF_SHA)):
            self.assertEqual(hashlib.sha256((ROOT/'vendor'/name).read_bytes()).hexdigest(),digest)

    def test_release_source_allowlist_excludes_user_storage(self):
        self.assertEqual(len(build.ALLOWLIST),len(set(build.ALLOWLIST)))
        for name in build.ALLOWLIST:
            self.assertFalse(any(part in ('data','workspace','exports','.build','.git','__pycache__','browser-profile') for part in Path(name).parts))
            self.assertTrue((ROOT/name).is_file(),name)
        self.assertIn('LICENSE',build.ALLOWLIST)
        self.assertIn('THIRD-PARTY-NOTICES.md',build.ALLOWLIST)
        self.assertIn('tests/browser_adversarial.cjs',build.ALLOWLIST)

    def test_offline_configuration_is_escaped_and_non_destructive(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='pkg-') as tmp:
            root=Path(tmp)/'fictional & local';root.mkdir()
            first=sandbox.create_configuration(root)
            self.assertTrue(first['created'])
            target=Path(first['path']);original=target.read_bytes();tree=ET.fromstring(original)
            for name in ('Networking','ClipboardRedirection','PrinterRedirection','AudioInput','VideoInput','vGPU'):
                self.assertEqual(tree.findtext(name),'Disable')
            maps=tree.findall('MappedFolders/MappedFolder')
            self.assertEqual([m.findtext('HostFolder') for m in maps],[str(root),str(root/'data')])
            self.assertEqual([m.findtext('ReadOnly') for m in maps],['true','false'])
            self.assertFalse(sandbox.create_configuration(root)['created'])
            self.assertEqual(target.read_bytes(),original)

    def test_configuration_refuses_hardlinked_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='pkg-') as tmp:
            root=Path(tmp);original=root/'fictional-marker.txt';original.write_text('fictional marker')
            try:os.link(original,root/'Private Accounting Offline.wsb')
            except OSError as exc:self.skipTest('Filesystem does not permit hardlinks: '+str(exc.errno))
            with self.assertRaises(ValueError):sandbox.create_configuration(root)
            self.assertEqual(original.read_text(),'fictional marker')

    def test_builder_refuses_hardlinked_source_or_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='pkg-') as tmp:
            root=Path(tmp);original=root/'fictional-marker.txt';original.write_text('fictional marker')
            linked=root/'source.txt'
            try:os.link(original,linked)
            except OSError as exc:self.skipTest('Filesystem does not permit hardlinks: '+str(exc.errno))
            with mock.patch.object(build,'ROOT',root):
                with self.assertRaises(ValueError):build.load_allowed('source.txt')
            with self.assertRaises(ValueError):build.check_local_path(linked)
            self.assertEqual(original.read_text(),'fictional marker')

    @unittest.skipUnless(os.name=='nt','Windows junction semantics')
    def test_windows_junctions_are_refused_without_symlink_privilege(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='pkg-') as tmp:
            root=Path(tmp);outside=root/'fictional-target';outside.mkdir()
            app=root/'app';app.mkdir();link=app/'data'
            self.assertTrue(outside.resolve().is_relative_to(root.resolve()))
            self.assertTrue(link.parent.resolve().is_relative_to(root.resolve()))
            quote=lambda p:"'"+str(p).replace("'","''")+"'"
            command="$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path "+quote(link)+" -Target "+quote(outside)+" | Out-Null"
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:self.skipTest('Windows did not permit a test junction.')
            try:
                with self.assertRaises(ValueError):sandbox.create_configuration(app)
                from server import Application
                with self.assertRaises(ValueError):Application(link)
                from finance_core import Store,FinanceError
                with self.assertRaises(FinanceError):Store(link).state()
            finally:os.rmdir(link)
            self.assertTrue(outside.is_dir())

if __name__=='__main__':unittest.main()
