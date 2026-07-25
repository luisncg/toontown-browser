import unittest

from toontown.toonbase import KeybindSettings


class StaticSettings:

    def __init__(self, bindings):
        self.bindings = bindings

    def getSetting(self, name, default):
        if name == KeybindSettings.SettingsKey:
            return self.bindings
        return default


class KeybindSettingsTests(unittest.TestCase):

    def test_default_movement_is_wasd(self):
        self.assertEqual(KeybindSettings.DefaultBindings['forward'], 'w')
        self.assertEqual(KeybindSettings.DefaultBindings['turnLeft'], 'a')
        self.assertEqual(KeybindSettings.DefaultBindings['reverse'], 's')
        self.assertEqual(KeybindSettings.DefaultBindings['turnRight'], 'd')
        self.assertEqual(
            KeybindSettings.getMovementInstruction(
                KeybindSettings.DefaultBindings
            ),
            'Use W, A, S, and D to move.',
        )

    def test_tutorial_instruction_follows_custom_bindings(self):
        bindings = dict(KeybindSettings.DefaultBindings)
        bindings.update({
            'forward': 'arrow_up',
            'turnLeft': 'arrow_left',
            'reverse': 'arrow_down',
            'turnRight': 'arrow_right',
        })
        self.assertEqual(
            KeybindSettings.getMovementInstruction(bindings),
            'Use the arrow keys to move.',
        )
        try:
            KeybindSettings.applyToConfig(StaticSettings(bindings))
            from toontown.toonbase import TTLocalizer
            self.assertEqual(
                TTLocalizer.QuestScriptTutorialMickey_4,
                'Come here! Use the arrow keys to move.',
            )
        finally:
            KeybindSettings.applyToConfig(
                StaticSettings(dict(KeybindSettings.DefaultBindings))
            )

    def test_trolley_movement_events_follow_active_bindings(self):
        bindings = dict(KeybindSettings.DefaultBindings)
        bindings.update({
            'forward': 'arrow_up',
            'reverse': 'arrow_down',
            'turnLeft': 'q',
            'turnRight': 'e',
            'jump': 'control',
        })
        try:
            KeybindSettings.applyToConfig(StaticSettings(bindings))
            self.assertEqual(
                KeybindSettings.getActiveMovementEvents(),
                {
                    'up': 'arrow_up',
                    'down': 'arrow_down',
                    'left': 'q',
                    'right': 'e',
                    'jump': 'control',
                },
            )
        finally:
            KeybindSettings.applyToConfig(
                StaticSettings(dict(KeybindSettings.DefaultBindings))
            )


if __name__ == '__main__':
    unittest.main()
