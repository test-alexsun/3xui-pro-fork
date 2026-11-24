"""Exercise the private backup primitive with a live WAL and corruption."""
from contextlib import closing
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class CandidateBackup(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'requires isolated root Linux')
    def test_online_snapshot_and_tamper_refusal(self):
        spec = importlib.util.spec_from_file_location('backup_candidate', Path(__file__).parents[2] / 'release/backup_candidate.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'awg'
            config.mkdir(mode=0o700)
            private = config / 'server.setconf'
            private.write_text('synthetic fixture, not a key')
            private.chmod(0o600)
            for name in ('client.conf', 'metadata.json'):
                path = config / name
                path.write_text('synthetic fixture')
                path.chmod(0o600)
            binary = root / 'binary'
            binary.write_text('fixture')
            binary.chmod(0o700)
            unit = root / 'unit'
            unit.write_text('fixture')
            database = root / 'x-ui.db'
            with closing(sqlite3.connect(database)) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE demo (name TEXT)')
                db.execute("INSERT INTO demo VALUES ('in-wal')")
                db.commit()
                database.chmod(0o600)
                snapshot = module.create_backup(backup_root=root / 'backups', database=database,
                    awg_dir=config, components={'panel': binary}, units={'panel.service': unit},
                    versions={'panel': '3.11.0'})
                manifest = module.verify_backup(snapshot)
                self.assertIn('awg/server.setconf', manifest['files'])
                self.assertEqual(manifest['source_metadata']['awg/server.setconf']['mode'], 0o600)
                self.assertEqual(manifest['source_metadata']['units/panel.service']['uid'], 0)
                with closing(sqlite3.connect(snapshot / 'database/x-ui.db')) as source:
                    with closing(sqlite3.connect(root / 'rehearsal.db')) as restored:
                        source.backup(restored)
                        self.assertEqual(restored.execute('SELECT name FROM demo').fetchall(), [('in-wal',)])
                        self.assertEqual(restored.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
                unexpected = snapshot / 'awg/unexpected'
                unexpected.write_text('unexpected')
                unexpected.chmod(0o600)
                with self.assertRaisesRegex(RuntimeError, 'inventory mismatch'):
                    module.verify_backup(snapshot)
                unexpected.unlink()
                (snapshot / 'awg/server.setconf').write_text('corrupted')
                with self.assertRaisesRegex(RuntimeError, 'integrity failure'):
                    module.verify_backup(snapshot)
                self.assertEqual(private.read_text(), 'synthetic fixture, not a key')

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'requires isolated root Linux')
    def test_external_managed_writer_is_refused(self):
        sys.path.insert(0, str(Path(__file__).parents[2] / 'release'))
        import prepare_candidate
        with tempfile.TemporaryDirectory() as tmp:
            managed = Path(tmp)
            path = managed / 'config'
            path.write_text('synthetic fixture')
            writer = subprocess.Popen([sys.executable, '-c',
                'import sys,time; f=open(sys.argv[1],"a"); print("ready",flush=True); time.sleep(30)', str(path)],
                stdout=subprocess.PIPE, text=True)
            old = prepare_candidate.DATA
            old_prefix, old_units = prepare_candidate.PREFIX, prepare_candidate.STOP_ORDER
            try:
                self.assertEqual(writer.stdout.readline().strip(), 'ready')
                prepare_candidate.DATA = managed
                prepare_candidate.PREFIX = managed / 'prefix'
                prepare_candidate.PREFIX.mkdir()
                prepare_candidate.STOP_ORDER = ()
                with self.assertRaisesRegex(RuntimeError, 'external process holds managed data writable'):
                    prepare_candidate.refuse_external_writers()
            finally:
                prepare_candidate.DATA = old
                prepare_candidate.PREFIX, prepare_candidate.STOP_ORDER = old_prefix, old_units
                writer.terminate()
                writer.wait(timeout=5)
                writer.stdout.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
