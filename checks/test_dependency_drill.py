"""Prevent the fault harness from selecting an ordinary running instance."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.dependency_drill import Drill


class DependencyDrillBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'rehearsal';self.output=Path(self.tmp.name)/'evidence'
        (self.root/'.rc/private').mkdir(parents=True)
        (self.root/'.rc/project.txt').write_text('adc_rc1_123456789abc\n')
        self.marker=self.root/'.rc/private/dependency-drill.json'

    def invoke(self):return Drill(self.root,self.output,'docker','explicit-local')

    def mark(self,**changes):
        self.marker.write_text(json.dumps(dict(project='adc_rc1_123456789abc',source='a'*40,port=18073)|changes))

    def test_unmarked_instance_never_contacts_docker(self):
        with patch.object(Drill,'run') as run:
            with self.assertRaises(FileNotFoundError):self.invoke()
        run.assert_not_called()

    def test_wrong_marker_project_never_contacts_docker(self):
        self.mark(project='adc_rc1_ffffffffffff')
        with patch.object(Drill,'run') as run:
            with self.assertRaises(ValueError):self.invoke()
        run.assert_not_called()

    def test_unidentified_application_never_contacts_docker(self):
        self.mark(source='unknown')
        with patch.object(Drill,'run') as run:
            with self.assertRaises(ValueError):self.invoke()
        run.assert_not_called()

    def test_remote_context_refused_before_container_operations(self):
        self.mark()
        with patch.object(Drill,'run',return_value=b'ssh://foreign') as run:
            with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(run.call_count,1)


if __name__=='__main__':unittest.main()
