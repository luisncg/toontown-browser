"""Actual Panda3D keyboard-event probe used by the canvas focus regression."""

from direct.showbase.DirectObject import DirectObject
from direct.showbase.InputStateGlobal import inputState

import browser_client
from direct.controls.ControlManager import ControlManager
from otp.settings.Settings import Settings
from toontown.toonbase import KeybindSettings


probe = DirectObject()
probe.accept("arrow_up", lambda: print("[BrowserInputTest] arrow-up"))
probe.accept("mouse1", lambda: print("[BrowserInputTest] mouse1"))

settings = Settings()
settings.readSettings()
KeybindSettings.applyToConfig(settings)
controlManager = ControlManager(enable=True)


def reportForward(isActive):
    if isActive:
        print("[BrowserInputTest] forward-on")


probe.accept(inputState.getEventName("forward"), reportForward)


def reportJump(isActive):
    if isActive:
        print("[BrowserInputTest] jump-on")


probe.accept(inputState.getEventName("jump"), reportJump)


def reportSprint(isActive):
    print("[BrowserInputTest] sprint-%s" % ("on" if isActive else "off"))


probe.accept(inputState.getEventName("sprint"), reportSprint)


def frame():
    browser_client.frame()
