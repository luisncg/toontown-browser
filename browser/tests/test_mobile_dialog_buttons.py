import builtins
import sys
import types
import unittest
from unittest.mock import patch

from panda3d.core import Filename, get_model_path, load_prc_file_data


load_prc_file_data(
    '',
    'window-type none\ndefault-directnotify-level warning\n'
    'default-model-extension .bam',
)
get_model_path().prepend_directory(Filename.from_os_specific('resources'))
builtins.__dev__ = False
builtins.__astron__ = True
builtins.game = type('Game', (), {'name': 'toontown'})()

from direct.showbase.ShowBase import ShowBase  # noqa: E402
from otp.otpgui import OTPDialog
from toontown.toontowngui import TTDialog


base = ShowBase(windowType='none')


class MobileDialogButtonTests(unittest.TestCase):

    def test_desktop_keeps_original_button_scale(self):
        with patch.dict(sys.modules, {'browser_storage': None}):
            self.assertEqual(OTPDialog.getDialogButtonScale(), 1.0)

    def test_portrait_mobile_enlarges_standard_dialog_buttons(self):
        storage = types.SimpleNamespace(
            get_item=lambda key: (
                '1' if key == OTPDialog.MobilePortraitRenderKey else None
            )
        )
        with patch.dict(sys.modules, {'browser_storage': storage}):
            self.assertEqual(
                OTPDialog.getDialogButtonScale(),
                OTPDialog.MobileDialogButtonScale,
            )

    def test_storage_failure_keeps_original_button_scale(self):
        def fail(_key):
            raise RuntimeError('storage unavailable')

        storage = types.SimpleNamespace(get_item=fail)
        with patch.dict(sys.modules, {'browser_storage': storage}):
            self.assertEqual(OTPDialog.getDialogButtonScale(), 1.0)

    def test_explicit_dialog_button_scale_is_preserved(self):
        options = {'button_scale': 0.8}
        OTPDialog.applyDefaultDialogButtonScale(options)
        self.assertEqual(options['button_scale'], 0.8)

    def test_default_dialog_button_scale_is_applied(self):
        options = {}
        with patch.object(OTPDialog, 'getDialogButtonScale',
                          return_value=1.35):
            OTPDialog.applyDefaultDialogButtonScale(options)
        self.assertEqual(options['button_scale'], 1.35)

    def test_mobile_scale_reaches_rendered_button(self):
        storage = types.SimpleNamespace(get_item=lambda _key: '1')
        with patch.dict(sys.modules, {'browser_storage': storage}):
            dialog = TTDialog.TTDialog(
                text='Touch-friendly dialog',
                style=TTDialog.Acknowledge,
                command=lambda _value: None,
            )
        try:
            rendered_scale = dialog.buttonList[0].getScale()
            self.assertAlmostEqual(rendered_scale.x, 1.35)
            self.assertAlmostEqual(rendered_scale.z, 1.35)
        finally:
            dialog.cleanup()


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        base.destroy()
