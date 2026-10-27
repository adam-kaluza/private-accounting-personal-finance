"""Fictional dependency-bootstrap cases; no external network is used."""
from pathlib import Path
import hashlib
import importlib.util
import io
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import bootstrap_runtime as bootstrap

class BootstrapTests(unittest.TestCase):
    def fixture(self):
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:archive.writestr('fictional.txt',b'fictional dependency')
        blob=output.getvalue()
        return blob,('fake.zip',hashlib.sha256(blob).hexdigest(),'runtime','https://example.invalid/fake.zip')

    def test_offline_archive_and_repeat_preserve_files(self):
        blob,source=self.fixture()
        with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='boot-') as directory,mock.patch.object(bootstrap,'SOURCES',(source,)):
            root=Path(directory);(root/'vendor').mkdir();(root/'vendor'/'fake.zip').write_bytes(blob)
            self.assertTrue(bootstrap.prepare(root)['prepared'])
            self.assertEqual((root/'runtime'/'fictional.txt').read_bytes(),b'fictional dependency')
            self.assertTrue(bootstrap.prepare(root)['prepared'])
            (root/'runtime'/'fictional.txt').write_text('fictional changed')
            with self.assertRaises(ValueError):bootstrap.prepare(root)
            self.assertEqual((root/'runtime'/'fictional.txt').read_text(),'fictional changed')

    def test_missing_archives_do_not_start_network(self):
        _,source=self.fixture()
        with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='boot-') as directory,mock.patch.object(bootstrap,'SOURCES',(source,)),mock.patch.object(bootstrap.urllib.request,'urlopen') as network:
            with self.assertRaises(ValueError):bootstrap.prepare(directory)
            network.assert_not_called()

    def test_bad_hash_preserves_existing_archive_without_extracting(self):
        _,source=self.fixture()
        with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='boot-') as directory,mock.patch.object(bootstrap,'SOURCES',(source,)):
            root=Path(directory);(root/'vendor').mkdir();path=root/'vendor'/'fake.zip';path.write_bytes(b'fictional wrong content')
            with self.assertRaises(ValueError):bootstrap.prepare(root)
            self.assertEqual(path.read_bytes(),b'fictional wrong content')
            self.assertFalse((root/'runtime').exists())

    def test_temporary_windows_lock_retry_never_overwrites_destination(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='boot-') as directory:
            root=Path(directory);staging=root/'staging';staging.mkdir();(staging/'fake.txt').write_text('fictional')
            destination=root/'runtime';real_rename=bootstrap.os.rename;attempts=[]
            def transient(source,target):
                attempts.append(True)
                if len(attempts)==1:raise PermissionError('Fictional temporary lock')
                return real_rename(source,target)
            with mock.patch.object(bootstrap.os,'rename',side_effect=transient),mock.patch.object(bootstrap.time,'sleep'):
                bootstrap.publish_directory(staging,destination)
            self.assertEqual(len(attempts),2)
            self.assertEqual((destination/'fake.txt').read_text(),'fictional')
            staging.mkdir()
            with self.assertRaises(ValueError):bootstrap.publish_directory(staging,destination)
            self.assertEqual((destination/'fake.txt').read_text(),'fictional')

if __name__=='__main__':unittest.main()
