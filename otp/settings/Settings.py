import json
import os

try:
    import browser_storage
except ImportError:
    browser_storage = None


class Settings:

    BrowserStorageKey = 'open-toontown.useropt.v1'

    def __init__(self):
        self.__settings = {}
        self.__filename = 'useropt.json'

    def doSavedSettingsExist(self):
        if browser_storage is not None:
            try:
                return browser_storage.get_item(self.BrowserStorageKey) is not None
            except RuntimeError:
                return False
        return os.path.exists(self.__filename)

    def readSettings(self):
        if not self.doSavedSettingsExist():
            self.__settings = {}
            return

        try:
            if browser_storage is not None:
                self.__settings = json.loads(browser_storage.get_item(self.BrowserStorageKey))
            else:
                with open(self.__filename, 'r') as f:
                    self.__settings = json.load(f)
        except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
            self.__settings = {}

    def writeSettings(self):
        if browser_storage is not None:
            browser_storage.set_item(
                self.BrowserStorageKey,
                json.dumps(self.__settings, separators=(',', ':')),
            )
        else:
            with open(self.__filename, 'w+') as f:
                json.dump(self.__settings, f, indent=4)

    def updateSetting(self, setting, value):
        self.__settings[setting] = value

    def getSetting(self, setting, default=None):
        return self.__settings.get(setting, default)
