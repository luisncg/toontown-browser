"""Persistent, user-editable bindings for avatar and gameplay controls."""

from panda3d.core import ConfigVariableString

try:
    import browser_storage
except ImportError:
    browser_storage = None


SettingsKey = 'key-bindings'

Actions = (
    'forward',
    'reverse',
    'turnLeft',
    'turnRight',
    'sprint',
    'jump',
    'viewGags',
    'viewToonTasks',
    'performAction',
    'exitActivity',
    'viewStreetMap',
)

DefaultBindings = {
    'forward': 'w',
    'reverse': 's',
    'turnLeft': 'a',
    'turnRight': 'd',
    'sprint': 'shift',
    'jump': 'space',
    'viewGags': 'home',
    'viewToonTasks': 'end',
    'performAction': 'delete',
    'exitActivity': 'escape',
    'viewStreetMap': 'alt',
}

MovementActions = {
    'up': 'forward',
    'down': 'reverse',
    'left': 'turnLeft',
    'right': 'turnRight',
    'jump': 'jump',
}

ConfigNames = {
    'forward': 'keybind-forward',
    'reverse': 'keybind-reverse',
    'turnLeft': 'keybind-turn-left',
    'turnRight': 'keybind-turn-right',
    'sprint': 'keybind-sprint',
    'jump': 'keybind-jump',
}

AllowedBindings = frozenset(
    tuple(chr(code) for code in range(ord('a'), ord('z') + 1))
    + tuple(str(number) for number in range(10))
    + (
        'arrow_up',
        'arrow_down',
        'arrow_left',
        'arrow_right',
        'space',
        'control',
        'shift',
        'alt',
        'home',
        'end',
        'delete',
        'escape',
    )
)

DisplayNames = {
    'arrow_up': 'Up Arrow',
    'arrow_down': 'Down Arrow',
    'arrow_left': 'Left Arrow',
    'arrow_right': 'Right Arrow',
    'space': 'Space',
    'control': 'Ctrl',
    'shift': 'Shift',
    'alt': 'Alt',
    'home': 'Home',
    'end': 'End',
    'delete': 'Delete',
    'escape': 'Esc',
}

_activeBindings = dict(DefaultBindings)
_freeCameraInputActive = False

BrowserChatSmokeFlag = 'open-toontown.keybind-chat-smoke'


def getBindings(settings):
    saved = settings.getSetting(SettingsKey, {})
    if isinstance(saved, dict):
        # Older browser builds only stored the five movement actions.  Merge
        # those values into the expanded defaults instead of discarding a
        # player's existing custom controls when the new rows first appear.
        merged = {
            action: saved.get(action, DefaultBindings[action])
            for action in Actions
        }
        # A player may already have assigned Shift to an older action.  Keep
        # that customization and give the newly introduced Sprint action the
        # first available fallback instead of rejecting their entire profile.
        if 'sprint' not in saved and merged['sprint'] in saved.values():
            fallbackBindings = (
                'control',
                'q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p',
                'a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l',
                'z', 'x', 'c', 'v', 'b', 'n', 'm',
            )
            usedBindings = tuple(saved.values())
            for binding in fallbackBindings:
                if binding not in usedBindings:
                    merged['sprint'] = binding
                    break
        bindings = [merged[action] for action in Actions]
        if (
            all(binding in AllowedBindings for binding in bindings)
            and len(set(bindings)) == len(Actions)
        ):
            return merged
    return dict(DefaultBindings)


def applyToConfig(settings):
    global _activeBindings
    bindings = getBindings(settings)
    _activeBindings = dict(bindings)
    for action, configName in ConfigNames.items():
        binding = bindings[action]
        ConfigVariableString(configName, DefaultBindings[action]).setValue(binding)
    _updateTutorialMovementText(bindings)
    return bindings


def saveBindings(settings, bindings):
    values = [bindings.get(action) for action in Actions]
    if (
        not all(binding in AllowedBindings for binding in values)
        or len(set(values)) != len(Actions)
    ):
        cleaned = dict(DefaultBindings)
    else:
        cleaned = dict(zip(Actions, values))
    settings.updateSetting(SettingsKey, cleaned)
    settings.writeSettings()
    applyToConfig(settings)
    return cleaned


def formatBinding(binding):
    return DisplayNames.get(binding, binding.upper())


def getMovementInstruction(bindings=None):
    """Describe the active movement quartet in familiar keyboard order."""
    if bindings is None:
        bindings = _activeBindings
    movementBindings = tuple(
        bindings[action]
        for action in ('forward', 'turnLeft', 'reverse', 'turnRight')
    )
    if movementBindings == ('arrow_up', 'arrow_left', 'arrow_down', 'arrow_right'):
        return 'Use the arrow keys to move.'
    names = tuple(formatBinding(binding) for binding in movementBindings)
    return 'Use %s, %s, %s, and %s to move.' % names


def _updateTutorialMovementText(bindings):
    # QuestParser reads these strings when the tutorial movie is assembled,
    # after ToonBase has loaded the player's browser settings.
    from toontown.toonbase import TTLocalizer
    instruction = getMovementInstruction(bindings)
    TTLocalizer.TutorialGreeting3 = 'Hi %s!\nCome over here!\n%s' % (
        '%s', instruction
    )
    TTLocalizer.QuestScriptTutorialMickey_4 = 'Come here! %s' % instruction


def getActiveBinding(action):
    return _activeBindings.get(action, DefaultBindings[action])


def getActiveEvent(action, released=False):
    event = getActiveBinding(action)
    if released:
        event += '-up'
    return event


def getActiveMovementEvents():
    """Return the current gameplay events used by movement-based activities."""
    return {
        direction: getActiveEvent(action)
        for direction, action in MovementActions.items()
    }


def isGameplayTypingKey(character):
    """Return whether a printable character is bound to a gameplay action."""
    if not isinstance(character, str) or len(character) != 1:
        return False
    key = character.lower()
    if _freeCameraInputActive and key in 'wasdqer':
        return True
    return any(
        len(binding) == 1 and binding == key
        for binding in _activeBindings.values()
    )


def setFreeCameraInputActive(active):
    global _freeCameraInputActive
    _freeCameraInputActive = bool(active)


def reportChatInputForSmoke(state, text=''):
    """Publish opt-in browser telemetry for the keybind/chat regression."""
    if browser_storage is None:
        return
    try:
        enabled = browser_storage.get_item(BrowserChatSmokeFlag) == '1'
    except RuntimeError:
        return
    if enabled:
        print('[BrowserChatInputTest] %s %s' % (state, text))
