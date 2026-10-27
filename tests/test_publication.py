"""Publication controls tested with fictional text only; no site files required."""
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('audit_publication',ROOT/'tools'/'audit_publication.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)

class PublicationTests(unittest.TestCase):
    def fixture(self):
        version='1.1.0';repo='https://github.com/example/fictional-finance';base=repo+'/releases/download/v'+version+'/'
        name='Private-Accounting-Personal-Finance-'+version+'-Windows-x64.zip';sha='1'*64
        script=("$ReleaseVersion = '"+version+"'\n$ArchiveSha256 = '"+sha+"'\n$ReleaseUrl = '"+base+name+"'\n").encode()
        installer_sha=audit.digest(script)
        config={'version':version,'status':'pre-release','tag':'v'+version,'repository_url':repo,
            'release_url':repo+'/releases/tag/v'+version,'zip_url':base+name,'checksum_url':base+name+'.sha256',
            'installer_url':base+'install.ps1','verification_url':base+'VERIFICATION-'+version+'.json',
            'guide_url':repo+'/blob/v'+version+'/docs/INSTALL.md','issues_url':repo+'/issues',
            'zip_sha256':sha,'installer_sha256':installer_sha,
            'install_command':"Invoke-WebRequest '"+base+"install.ps1' -OutFile $p; if ((Get-FileHash $p -Algorithm SHA256).Hash -ne '"+installer_sha+"') {throw 'Mismatch'}; & $p"}
        return config,script,sha,name

    def test_public_paths_reject_traversal_storage_and_duplicates(self):
        for names in (['../private.txt'],['/absolute'],['app\\file.py'],['app/../x'],['data/x.json'],['workspace/x'],['vendor/archive.zip'],['runtime/python.exe'],['a.py','a.py'],['App/main.py','app/main.py'],['a//b.py']):
            with self.assertRaises(audit.AuditError):audit.canonical_paths(names)
        self.assertEqual(audit.canonical_paths(['app/main.py','.github/workflows/ci.yml']),['.github/workflows/ci.yml','app/main.py'])

    def test_reuses_patterns_without_whole_scanner_exemption(self):
        source=b"def build():\n    forbidden=[rb'PRIVATE_SENTINEL']\n    return 1\n"
        patterns,body=audit.package_patterns(source)
        self.assertEqual(patterns,[b'PRIVATE_SENTINEL'])
        audit.scan_content('tools/build_release.py',source,patterns,body)
        contaminated=source+b"\nsecret='PRIVATE_SENTINEL'\n"
        patterns,body=audit.package_patterns(contaminated)
        with self.assertRaises(audit.AuditError):audit.scan_content('tools/build_release.py',contaminated,patterns,body)

    def test_empty_or_dynamic_package_patterns_fail_closed(self):
        for source in (b'forbidden=[]',b'forbidden=get_patterns()',b'x=1'):
            with self.assertRaises(audit.AuditError):audit.package_patterns(source)

    def test_matching_content_is_never_in_error(self):
        secret=b'ghp_'+b'a'*40
        with self.assertRaises(audit.AuditError) as caught:audit.scan_content('README.md',secret,[])
        self.assertNotIn(secret.decode(),str(caught.exception))

    def test_unlisted_storage_is_not_traversed(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='pub-') as tmp:
            root=Path(tmp);(root/'public.md').write_text('Fictional public example')
            (root/'data').mkdir();(root/'data'/'fictional.txt').write_text('Not part of this audit')
            self.assertEqual(audit.read_source(root,'public.md'),b'Fictional public example')
            with self.assertRaises(audit.AuditError):audit.read_source(root,'data/fictional.txt')

    def test_complete_pins_pass(self):
        self.assertTrue(audit.verify_public_pins(*self.fixture())['consistent'])

    def test_changed_zip_or_installer_hash_fails(self):
        for key in ('zip_sha256','installer_sha256'):
            config,script,sha,name=self.fixture();config[key]='0'*64
            with self.assertRaises(audit.AuditError):audit.verify_public_pins(config,script,sha,name)

    def test_wrong_repository_tag_or_guide_fails(self):
        for key in ('repository_url','tag','zip_url','installer_url','verification_url','guide_url','issues_url'):
            config,script,sha,name=self.fixture();config[key]='https://example.invalid/fictional'
            with self.assertRaises(audit.AuditError):audit.verify_public_pins(config,script,sha,name)

    def test_installer_pin_mismatch_fails(self):
        config,script,sha,name=self.fixture();script=script.replace(b"$ReleaseVersion = '1.1.0'",b"$ReleaseVersion = '9.9.9'")
        config['installer_sha256']=audit.digest(script)
        with self.assertRaises(audit.AuditError):audit.verify_public_pins(config,script,sha,name)

    def test_archive_filename_version_mismatch_fails(self):
        config,script,sha,name=self.fixture()
        with self.assertRaises(audit.AuditError):audit.verify_public_pins(config,script,sha,name.replace('1.1.0','9.9.9'))

    def test_unverified_pipe_or_policy_change_fails(self):
        for suffix in ('; iex $x','; Invoke-Expression $x','; Set-ExecutionPolicy Unrestricted'):
            config,script,sha,name=self.fixture();config['install_command']+=suffix
            with self.assertRaises(audit.AuditError):audit.verify_public_pins(config,script,sha,name)

    def test_missing_checksum_verification_fails(self):
        config,script,sha,name=self.fixture();config['install_command']='& install.ps1'
        with self.assertRaises(audit.AuditError):audit.verify_public_pins(config,script,sha,name)

    def test_script_execution_before_hash_check_fails(self):
        for before in ('& $p; ','& ([ScriptBlock]::Create($text)); '):
            config,script,sha,name=self.fixture();config['install_command']=before+config['install_command']
            with self.assertRaises(audit.AuditError):audit.verify_public_pins(config,script,sha,name)

    def test_verified_scriptblock_shape_is_accepted_but_not_claimed_proven(self):
        config,script,sha,name=self.fixture();config['install_command']=config['install_command'].replace('& $p','& ([ScriptBlock]::Create($text))')
        result=audit.verify_public_pins(config,script,sha,name)
        self.assertTrue(result['bootstrap_structure_checked'])
        self.assertFalse(result['powershell_semantics_proven_by_static_check'])

    def test_dotnet_sha256_checked_before_execution(self):
        config,script,sha,name=self.fixture()
        command=("$url='"+config['installer_url']+"'; $h=[System.Security.Cryptography.SHA256]::Create(); "
                 "$actual=[BitConverter]::ToString($h.ComputeHash($bytes)).Replace('-','').ToLowerInvariant(); "
                 "if($actual -ne '"+config['installer_sha256']+"'){throw 'Mismatch'}; & ([ScriptBlock]::Create($text))")
        config['install_command']=command
        self.assertTrue(audit.verify_public_pins(config,script,sha,name)['bootstrap_structure_checked'])
        for bad in ('& ([ScriptBlock]::Create($text)); '+command,
                    command.replace('Cryptography.SHA256','Cryptography.MD5'),
                    command.replace('$h.ComputeHash','$different.ComputeHash'),
                    command.replace('$h.ComputeHash','$h.ToString'),
                    command.replace("if($actual -ne '","& ([ScriptBlock]::Create($text)); if($actual -ne '")):
            config['install_command']=bad
            with self.assertRaises(audit.AuditError):audit.verify_public_pins(config,script,sha,name)

if __name__=='__main__':unittest.main()
