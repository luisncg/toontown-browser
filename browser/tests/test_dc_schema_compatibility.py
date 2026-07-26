import os
import subprocess
import tempfile
import unittest

from panda3d.direct import DCFile


PROJECT_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..'))


def load_dc(path):
    dc = DCFile()
    if not dc.read(path):
        raise AssertionError('could not read %s' % path)
    return dc


class DCSchemaCompatibilityTests(unittest.TestCase):
    def test_every_existing_class_and_field_number_is_preserved(self):
        baselineText = subprocess.check_output(
            ['git', 'show', 'HEAD:etc/toon.dc'],
            cwd=PROJECT_ROOT)
        with tempfile.NamedTemporaryFile(suffix='.dc') as baselineFile:
            baselineFile.write(baselineText)
            baselineFile.flush()
            baseline = load_dc(baselineFile.name)
            current = load_dc(os.path.join(PROJECT_ROOT, 'etc', 'toon.dc'))

        for index in range(baseline.get_num_classes()):
            expectedClass = baseline.get_class(index)
            currentClass = current.get_class_by_name(expectedClass.get_name())
            self.assertIsNotNone(currentClass, expectedClass.get_name())
            self.assertEqual(
                currentClass.get_number(),
                expectedClass.get_number(),
                expectedClass.get_name())
            for fieldIndex in range(expectedClass.get_num_fields()):
                expectedField = expectedClass.get_field(fieldIndex)
                currentField = currentClass.get_field_by_name(
                    expectedField.get_name())
                self.assertIsNotNone(
                    currentField,
                    '%s.%s' %
                    (expectedClass.get_name(), expectedField.get_name()))
                self.assertEqual(
                    currentField.get_number(),
                    expectedField.get_number(),
                    '%s.%s' %
                    (expectedClass.get_name(), expectedField.get_name()))


if __name__ == '__main__':
    unittest.main()
