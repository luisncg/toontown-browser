import unittest

from direct.showbase.ShowBase import ShowBase

from toontown.toonbase import KeybindSettings


class StaticSettings:

    def __init__(self, bindings):
        self.bindings = bindings

    def getSetting(self, name, default):
        if name == KeybindSettings.SettingsKey:
            return self.bindings
        return default


class FakeButtonThrowerNode:

    def __init__(self):
        self.modifiers = None

    def getModifierButtons(self):
        return self.modifiers

    def setModifierButtons(self, modifiers):
        self.modifiers = modifiers


class FakeButtonThrower:

    def __init__(self):
        self.throwerNode = FakeButtonThrowerNode()

    def node(self):
        return self.throwerNode


class TrolleyKeybindTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.base = ShowBase(windowType='none')
        cls.base.buttonThrowers = [FakeButtonThrower()]

    @classmethod
    def tearDownClass(cls):
        cls.base.destroy()

    def tearDown(self):
        KeybindSettings.applyToConfig(
            StaticSettings(dict(KeybindSettings.DefaultBindings))
        )

    def test_default_wasd_drives_shared_trolley_arrow_state(self):
        from toontown.minigame.ArrowKeys import ArrowKeys

        keys = ArrowKeys()
        try:
            self.assertEqual(
                (keys.UP_KEY, keys.LEFT_KEY, keys.DOWN_KEY, keys.RIGHT_KEY),
                ('w', 'a', 's', 'd'),
            )
            self.base.messenger.send('w')
            self.assertTrue(keys.upPressed())
            self.base.messenger.send('w-up')
            self.assertFalse(keys.upPressed())
        finally:
            keys.destroy()

    def test_custom_movement_bindings_drive_trolley_state(self):
        from toontown.minigame.ArrowKeys import ArrowKeys

        bindings = dict(KeybindSettings.DefaultBindings)
        bindings.update({
            'forward': 'arrow_up',
            'reverse': 'arrow_down',
            'turnLeft': 'q',
            'turnRight': 'e',
            'jump': 'control',
        })
        KeybindSettings.applyToConfig(StaticSettings(bindings))
        keys = ArrowKeys()
        try:
            self.assertEqual(
                (
                    keys.UP_KEY,
                    keys.LEFT_KEY,
                    keys.DOWN_KEY,
                    keys.RIGHT_KEY,
                    keys.JUMP_KEY,
                ),
                ('arrow_up', 'q', 'arrow_down', 'e', 'control'),
            )
            self.base.messenger.send('q')
            self.assertTrue(keys.leftPressed())
            self.base.messenger.send('q-up')
            self.assertFalse(keys.leftPressed())
        finally:
            keys.destroy()


if __name__ == '__main__':
    unittest.main()
