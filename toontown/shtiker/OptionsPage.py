from panda3d.core import *
from . import ShtikerPage
from toontown.toontowngui import TTDialog
from direct.gui.DirectGui import *
from toontown.toonbase import TTLocalizer
from toontown.toonbase import KeybindSettings
from . import DisplaySettingsDialog
from direct.task import Task
from otp.speedchat import SpeedChat
from otp.speedchat import SCColorScheme
from otp.speedchat import SCStaticTextTerminal
from direct.directnotify import DirectNotifyGlobal
from enum import IntEnum

try:
    import browser_storage
except ImportError:
    browser_storage = None
speedChatStyles = ((2000,
  (200 / 255.0, 60 / 255.0, 229 / 255.0),
  (200 / 255.0, 135 / 255.0, 255 / 255.0),
  (220 / 255.0, 195 / 255.0, 229 / 255.0)),
 (2001,
  (0 / 255.0, 0 / 255.0, 255 / 255.0),
  (140 / 255.0, 150 / 255.0, 235 / 255.0),
  (201 / 255.0, 215 / 255.0, 255 / 255.0)),
 (2002,
  (90 / 255.0, 175 / 255.0, 225 / 255.0),
  (120 / 255.0, 215 / 255.0, 255 / 255.0),
  (208 / 255.0, 230 / 255.0, 250 / 255.0)),
 (2003,
  (130 / 255.0, 235 / 255.0, 235 / 255.0),
  (120 / 255.0, 225 / 255.0, 225 / 255.0),
  (234 / 255.0, 255 / 255.0, 255 / 255.0)),
 (2004,
  (0 / 255.0, 200 / 255.0, 70 / 255.0),
  (0 / 255.0, 200 / 255.0, 80 / 255.0),
  (204 / 255.0, 255 / 255.0, 204 / 255.0)),
 (2005,
  (235 / 255.0, 230 / 255.0, 0 / 255.0),
  (255 / 255.0, 250 / 255.0, 100 / 255.0),
  (255 / 255.0, 250 / 255.0, 204 / 255.0)),
 (2006,
  (255 / 255.0, 153 / 255.0, 0 / 255.0),
  (229 / 255.0, 147 / 255.0, 0 / 255.0),
  (255 / 255.0, 234 / 255.0, 204 / 255.0)),
 (2007,
  (255 / 255.0, 0 / 255.0, 50 / 255.0),
  (229 / 255.0, 0 / 255.0, 50 / 255.0),
  (255 / 255.0, 204 / 255.0, 204 / 255.0)),
 (2008,
  (255 / 255.0, 153 / 255.0, 193 / 255.0),
  (240 / 255.0, 157 / 255.0, 192 / 255.0),
  (255 / 255.0, 215 / 255.0, 238 / 255.0)),
 (2009,
  (170 / 255.0, 120 / 255.0, 20 / 255.0),
  (165 / 255.0, 120 / 255.0, 50 / 255.0),
  (210 / 255.0, 200 / 255.0, 180 / 255.0)))
PageMode = IntEnum('PageMode', ('Options', 'Advanced', 'Codes'), start=0)

class OptionsPage(ShtikerPage.ShtikerPage):
    notify = DirectNotifyGlobal.directNotify.newCategory('OptionsPage')

    def __init__(self):
        ShtikerPage.ShtikerPage.__init__(self)

    def load(self):
        ShtikerPage.ShtikerPage.load(self)
        self.optionsTabPage = OptionsTabPage(self)
        self.optionsTabPage.hide()
        self.advancedTabPage = AdvancedSettingsPage(self)
        self.advancedTabPage.hide()
        self.codesTabPage = CodesTabPage(self)
        self.codesTabPage.hide()
        titleHeight = 0.61
        self.title = DirectLabel(parent=self, relief=None, text=TTLocalizer.OptionsPageTitle, text_scale=0.12, pos=(0, 0, titleHeight))
        normalColor = (1, 1, 1, 1)
        clickColor = (0.8, 0.8, 0, 1)
        rolloverColor = (0.15, 0.82, 1.0, 1)
        diabledColor = (1.0, 0.98, 0.15, 1)
        gui = loader.loadModel('phase_3.5/models/gui/fishingBook')
        self.optionsTab = DirectButton(parent=self, relief=None, text=TTLocalizer.OptionsPageTitle, text_scale=TTLocalizer.OPoptionsTab, text_align=TextNode.ALeft, text_pos=(0.01, 0.0, 0.0), image=gui.find('**/tabs/polySurface1'), image_pos=(0.55, 1, -0.91), image_hpr=(0, 0, -90), image_scale=(0.033, 0.033, 0.035), image_color=normalColor, image1_color=clickColor, image2_color=rolloverColor, image3_color=diabledColor, text_fg=Vec4(0.2, 0.1, 0, 1), command=self.setMode, extraArgs=[PageMode.Options], pos=(-0.57, 0, 0.77))
        self.advancedTab = DirectButton(parent=self, relief=None, text=TTLocalizer.OptionsPageAdvancedTab, text_scale=0.055, text_align=TextNode.ALeft, text_pos=(-0.01, 0.0, 0.0), image=gui.find('**/tabs/polySurface1'), image_pos=(0.55, 1, -0.91), image_hpr=(0, 0, -90), image_scale=(0.033, 0.033, 0.035), image_color=normalColor, image1_color=clickColor, image2_color=rolloverColor, image3_color=diabledColor, text_fg=Vec4(0.2, 0.1, 0, 1), command=self.setMode, extraArgs=[PageMode.Advanced], pos=(-0.10, 0, 0.77))
        self.codesTab = DirectButton(parent=self, relief=None, text=TTLocalizer.OptionsPageCodesTab, text_scale=0.055, text_align=TextNode.ALeft, text_pos=(-0.035, 0.0, 0.0), image=gui.find('**/tabs/polySurface2'), image_pos=(0.12, 1, -0.91), image_hpr=(0, 0, -90), image_scale=(0.033, 0.033, 0.035), image_color=normalColor, image1_color=clickColor, image2_color=rolloverColor, image3_color=diabledColor, text_fg=Vec4(0.2, 0.1, 0, 1), command=self.setMode, extraArgs=[PageMode.Codes], pos=(0.37, 0, 0.77))
        return

    def enter(self):
        self.setMode(PageMode.Options, updateAnyways=1)
        ShtikerPage.ShtikerPage.enter(self)

    def exit(self):
        self.optionsTabPage.exit()
        self.advancedTabPage.exit()
        self.codesTabPage.exit()
        ShtikerPage.ShtikerPage.exit(self)

    def unload(self):
        self.optionsTabPage.unload()
        self.advancedTabPage.unload()
        self.codesTabPage.unload()
        del self.title
        ShtikerPage.ShtikerPage.unload(self)

    def setMode(self, mode, updateAnyways = 0):
        messenger.send('wakeup')
        if not updateAnyways:
            if self.mode == mode:
                return
            else:
                self.mode = mode
        if mode == PageMode.Options:
            self.mode = PageMode.Options
            self.title['text'] = TTLocalizer.OptionsPageTitle
            self.optionsTab['state'] = DGG.DISABLED
            self.optionsTabPage.enter()
            self.advancedTab['state'] = DGG.NORMAL
            self.advancedTabPage.exit()
            self.codesTab['state'] = DGG.NORMAL
            self.codesTabPage.exit()
        elif mode == PageMode.Advanced:
            self.mode = PageMode.Advanced
            self.title['text'] = TTLocalizer.AdvancedSettingsTitle
            self.optionsTab['state'] = DGG.NORMAL
            self.optionsTabPage.exit()
            self.advancedTab['state'] = DGG.DISABLED
            self.codesTab['state'] = DGG.NORMAL
            self.codesTabPage.exit()
            self.advancedTabPage.enter()
        elif mode == PageMode.Codes:
            self.mode = PageMode.Codes
            self.title['text'] = TTLocalizer.CdrPageTitle
            self.optionsTab['state'] = DGG.NORMAL
            self.optionsTabPage.exit()
            self.advancedTab['state'] = DGG.NORMAL
            self.advancedTabPage.exit()
            self.codesTab['state'] = DGG.DISABLED
            self.codesTabPage.enter()
        else:
            raise Exception('OptionsPage::setMode - Invalid Mode %s' % mode)


class OptionsTabPage(DirectFrame):
    notify = DirectNotifyGlobal.directNotify.newCategory('OptionsTabPage')

    def __init__(self, parent = aspect2d):
        self._parent = parent
        self.currentSizeIndex = None
        DirectFrame.__init__(self, parent=self._parent, relief=None, pos=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0))
        self.load()
        return

    def destroy(self):
        self._parent = None
        DirectFrame.destroy(self)
        return

    def load(self):
        guiButton = loader.loadModel('phase_3/models/gui/quit_button')
        gui = loader.loadModel('phase_3.5/models/gui/friendslist_gui')
        titleHeight = 0.61
        textStartHeight = 0.45
        textRowHeight = 0.145
        leftMargin = -0.72
        buttonbase_xcoord = 0.35
        buttonbase_ycoord = 0.45
        button_image_scale = (0.7, 1, 1)
        button_textpos = (0, -0.02)
        options_text_scale = 0.052
        disabled_arrow_color = Vec4(0.6, 0.6, 0.6, 1.0)
        self.speed_chat_scale = 0.055
        self.Friends_Label = DirectLabel(parent=self, relief=None, text='', text_align=TextNode.ALeft, text_scale=options_text_scale, text_wordwrap=16, pos=(leftMargin, 0, textStartHeight))
        self.Whispers_Label = DirectLabel(parent=self, relief=None, text='', text_align=TextNode.ALeft, text_scale=options_text_scale, text_wordwrap=16, pos=(leftMargin, 0, textStartHeight - textRowHeight))
        self.SpeedChatStyle_Label = DirectLabel(parent=self, relief=None, text=TTLocalizer.OptionsPageSpeedChatStyleLabel, text_align=TextNode.ALeft, text_scale=options_text_scale, text_wordwrap=10, pos=(leftMargin, 0, textStartHeight - 2 * textRowHeight))
        self.Friends_toggleButton = DirectButton(parent=self, relief=None, image=(guiButton.find('**/QuitBtn_UP'), guiButton.find('**/QuitBtn_DN'), guiButton.find('**/QuitBtn_RLVR')), image_scale=button_image_scale, text='', text_scale=options_text_scale, text_pos=button_textpos, pos=(buttonbase_xcoord, 0.0, buttonbase_ycoord), command=self.__doToggleAcceptFriends)
        self.Whispers_toggleButton = DirectButton(parent=self, relief=None, image=(guiButton.find('**/QuitBtn_UP'), guiButton.find('**/QuitBtn_DN'), guiButton.find('**/QuitBtn_RLVR')), image_scale=button_image_scale, text='', text_scale=options_text_scale, text_pos=button_textpos, pos=(buttonbase_xcoord, 0.0, buttonbase_ycoord - textRowHeight), command=self.__doToggleAcceptWhispers)
        self.speedChatStyleLeftArrow = DirectButton(parent=self, relief=None, image=(gui.find('**/Horiz_Arrow_UP'),
         gui.find('**/Horiz_Arrow_DN'),
         gui.find('**/Horiz_Arrow_Rllvr'),
         gui.find('**/Horiz_Arrow_UP')), image3_color=Vec4(1, 1, 1, 0.5), scale=(-1.0, 1.0, 1.0), pos=(0.25, 0, buttonbase_ycoord - textRowHeight * 2), command=self.__doSpeedChatStyleLeft)
        self.speedChatStyleRightArrow = DirectButton(parent=self, relief=None, image=(gui.find('**/Horiz_Arrow_UP'),
         gui.find('**/Horiz_Arrow_DN'),
         gui.find('**/Horiz_Arrow_Rllvr'),
         gui.find('**/Horiz_Arrow_UP')), image3_color=Vec4(1, 1, 1, 0.5), pos=(0.65, 0, buttonbase_ycoord - textRowHeight * 2), command=self.__doSpeedChatStyleRight)
        self.speedChatStyleText = SpeedChat.SpeedChat(name='OptionsPageStyleText', structure=[2000], backgroundModelName='phase_3/models/gui/ChatPanel', guiModelName='phase_3.5/models/gui/speedChatGui')
        self.speedChatStyleText.setScale(self.speed_chat_scale)
        self.speedChatStyleText.setPos(0.37, 0, buttonbase_ycoord - textRowHeight * 2 + 0.03)
        self.speedChatStyleText.reparentTo(self, DGG.FOREGROUND_SORT_INDEX)
        self.exitButton = DirectButton(parent=self, relief=None, image=(guiButton.find('**/QuitBtn_UP'), guiButton.find('**/QuitBtn_DN'), guiButton.find('**/QuitBtn_RLVR')), image_scale=1.15, text=TTLocalizer.OptionsPageExitToontown, text_scale=options_text_scale, text_pos=button_textpos, textMayChange=0, pos=(0.45, 0, -0.6), command=self.__handleExitShowWithConfirm)
        guiButton.removeNode()
        gui.removeNode()
        return

    def enter(self):
        self.show()
        self.settingsChanged = 0
        self.__setAcceptFriendsButton()
        self.__setAcceptWhispersButton()
        self.speedChatStyleText.enter()
        self.speedChatStyleIndex = base.localAvatar.getSpeedChatStyleIndex()
        self.updateSpeedChatStyle()
        if self._parent.book.safeMode:
            self.exitButton.hide()
        else:
            self.exitButton.show()

    def exit(self):
        self.ignore('confirmDone')
        self.hide()
        if self.settingsChanged != 0:
            base.settings.writeSettings()
        self.speedChatStyleText.exit()

    def unload(self):
        self.exitButton.destroy()
        self.Friends_toggleButton.destroy()
        self.Whispers_toggleButton.destroy()
        self.speedChatStyleLeftArrow.destroy()
        self.speedChatStyleRightArrow.destroy()
        del self.exitButton
        del self.Friends_Label
        del self.Whispers_Label
        del self.SpeedChatStyle_Label
        del self.Friends_toggleButton
        del self.Whispers_toggleButton
        del self.speedChatStyleLeftArrow
        del self.speedChatStyleRightArrow
        self.speedChatStyleText.exit()
        self.speedChatStyleText.destroy()
        del self.speedChatStyleText
        self.currentSizeIndex = None
        return

    def __doToggleAcceptFriends(self):
        messenger.send('wakeup')
        if base.localAvatar.acceptingNewFriends:
            base.localAvatar.acceptingNewFriends = 0
            base.settings.updateSetting('accepting-new-friends', False)
        else:
            base.localAvatar.acceptingNewFriends = 1
            base.settings.updateSetting('accepting-new-friends', True)
        self.settingsChanged = 1
        self.__setAcceptFriendsButton()

    def __doToggleAcceptWhispers(self):
        messenger.send('wakeup')
        if base.localAvatar.acceptingNonFriendWhispers:
            base.localAvatar.acceptingNonFriendWhispers = 0
            base.settings.updateSetting('accepting-non-friend-whispers', False)
        else:
            base.localAvatar.acceptingNonFriendWhispers = 1
            base.settings.updateSetting('accepting-non-friend-whispers', True)
        self.settingsChanged = 1
        self.__setAcceptWhispersButton()

    def __setAcceptFriendsButton(self):
        if base.localAvatar.acceptingNewFriends:
            self.Friends_Label['text'] = TTLocalizer.OptionsPageFriendsEnabledLabel
            self.Friends_toggleButton['text'] = TTLocalizer.OptionsPageToggleOff
        else:
            self.Friends_Label['text'] = TTLocalizer.OptionsPageFriendsDisabledLabel
            self.Friends_toggleButton['text'] = TTLocalizer.OptionsPageToggleOn

    def __setAcceptWhispersButton(self):
        if base.localAvatar.acceptingNonFriendWhispers:
            self.Whispers_Label['text'] = TTLocalizer.OptionsPageWhisperEnabledLabel
            self.Whispers_toggleButton['text'] = TTLocalizer.OptionsPageToggleOff
        else:
            self.Whispers_Label['text'] = TTLocalizer.OptionsPageWhisperDisabledLabel
            self.Whispers_toggleButton['text'] = TTLocalizer.OptionsPageToggleOn

    def __doSpeedChatStyleLeft(self):
        if self.speedChatStyleIndex > 0:
            self.speedChatStyleIndex = self.speedChatStyleIndex - 1
            self.updateSpeedChatStyle()

    def __doSpeedChatStyleRight(self):
        if self.speedChatStyleIndex < len(speedChatStyles) - 1:
            self.speedChatStyleIndex = self.speedChatStyleIndex + 1
            self.updateSpeedChatStyle()

    def updateSpeedChatStyle(self):
        nameKey, arrowColor, rolloverColor, frameColor = speedChatStyles[self.speedChatStyleIndex]
        newSCColorScheme = SCColorScheme.SCColorScheme(arrowColor=arrowColor, rolloverColor=rolloverColor, frameColor=frameColor)
        self.speedChatStyleText.setColorScheme(newSCColorScheme)
        self.speedChatStyleText.clearMenu()
        colorName = SCStaticTextTerminal.SCStaticTextTerminal(nameKey)
        self.speedChatStyleText.append(colorName)
        self.speedChatStyleText.finalize()
        self.speedChatStyleText.setPos(0.445 - self.speedChatStyleText.getWidth() * self.speed_chat_scale / 2, 0, self.speedChatStyleText.getPos()[2])
        if self.speedChatStyleIndex > 0:
            self.speedChatStyleLeftArrow['state'] = DGG.NORMAL
        else:
            self.speedChatStyleLeftArrow['state'] = DGG.DISABLED
        if self.speedChatStyleIndex < len(speedChatStyles) - 1:
            self.speedChatStyleRightArrow['state'] = DGG.NORMAL
        else:
            self.speedChatStyleRightArrow['state'] = DGG.DISABLED
        base.localAvatar.b_setSpeedChatStyleIndex(self.speedChatStyleIndex)

    def __handleExitShowWithConfirm(self):
        self.confirm = TTDialog.TTGlobalDialog(doneEvent='confirmDone', message=TTLocalizer.OptionsPageExitConfirm, style=TTDialog.TwoChoice)
        self.confirm.show()
        self._parent.doneStatus = {'mode': 'exit',
         'exitTo': 'closeShard'}
        self.accept('confirmDone', self.__handleConfirm)

    def __handleConfirm(self):
        status = self.confirm.doneStatus
        self.ignore('confirmDone')
        self.confirm.cleanup()
        del self.confirm
        if status == 'ok':
            base.cr._userLoggingOut = True
            messenger.send(self._parent.doneEvent)


class AdvancedSettingsPage(DirectFrame):
    notify = DirectNotifyGlobal.directNotify.newCategory('AdvancedSettingsPage')
    CaptureEvent = 'advanced-settings-key-down'
    CaptureTaskName = 'advanced-settings-key-capture'
    CapturedKeyStorageKey = 'open-toontown.captured-key'
    DisplaySettingsTaskName = 'save-display-settings'
    DisplaySettingsDelay = 60
    ChangeDisplaySettings = ConfigVariableBool('change-display-settings', 1).value
    ChangeDisplayAPI = ConfigVariableBool('change-display-api', 0).value

    GameplayTab = 'gameplay'
    ControlsTab = 'controls'
    AudioTab = 'audio'
    VideoTab = 'video'
    Tabs = (GameplayTab, ControlsTab, AudioTab, VideoTab)
    TabViewport = (-0.74, 0.78, -0.61, 0.34)
    TabContentBottoms = {
        GameplayTab: -0.61,
        ControlsTab: -1.51,
        AudioTab: -0.61,
        VideoTab: -0.61,
    }

    TabLabels = {
        GameplayTab: TTLocalizer.AdvancedSettingsGameplayTab,
        ControlsTab: TTLocalizer.AdvancedSettingsControlsTab,
        AudioTab: TTLocalizer.AdvancedSettingsAudioTab,
        VideoTab: TTLocalizer.AdvancedSettingsVideoTab,
    }

    ActionLabels = {
        'forward': TTLocalizer.AdvancedSettingsMoveForward,
        'reverse': TTLocalizer.AdvancedSettingsMoveBackward,
        'turnLeft': TTLocalizer.AdvancedSettingsTurnLeft,
        'turnRight': TTLocalizer.AdvancedSettingsTurnRight,
        'sprint': TTLocalizer.AdvancedSettingsSprint,
        'jump': TTLocalizer.AdvancedSettingsJump,
        'viewGags': TTLocalizer.AdvancedSettingsViewGags,
        'viewToonTasks': TTLocalizer.AdvancedSettingsViewToonTasks,
        'performAction': TTLocalizer.AdvancedSettingsPerformAction,
        'exitActivity': TTLocalizer.AdvancedSettingsExitActivity,
        'viewStreetMap': TTLocalizer.AdvancedSettingsViewStreetMap,
    }

    def __init__(self, parent=aspect2d):
        self._parent = parent
        self.captureAction = None
        self.captureButtons = {}
        self.captureButtonsDown = set()
        self.browserKeyCapture = False
        self.savedButtonThrowers = []
        self.bindingButtons = {}
        self.actionLabels = {}
        self.tabButtons = {}
        self.tabFrames = {}
        self.tabCanvases = {}
        self.activeTab = None
        self.displaySettings = None
        self.displaySettingsChanged = 0
        self.displaySettingsSize = (None, None)
        self.displaySettingsFullscreen = None
        self.displaySettingsEmbedded = None
        self.displaySettingsApi = None
        self.displaySettingsApiChanged = 0
        DirectFrame.__init__(
            self,
            parent=self._parent,
            relief=None,
            pos=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
        )
        self.load()

    def load(self):
        guiButton = loader.loadModel('phase_3/models/gui/quit_button')
        buttonImages = (
            guiButton.find('**/QuitBtn_UP'),
            guiButton.find('**/QuitBtn_DN'),
            guiButton.find('**/QuitBtn_RLVR'),
        )

        tabXPositions = (-0.57, -0.19, 0.19, 0.57)
        for tab, tabX in zip(self.Tabs, tabXPositions):
            self.tabButtons[tab] = DirectButton(
                parent=self,
                relief=None,
                image=buttonImages,
                image_scale=(0.68, 1, 0.72),
                text=self.TabLabels[tab],
                text_scale=0.042,
                text_pos=(0, -0.017),
                pos=(tabX, 0, 0.445),
                command=self.__setTab,
                extraArgs=[tab],
            )
            self.tabFrames[tab] = DirectScrolledFrame(
                parent=self,
                relief=None,
                frameColor=(0, 0, 0, 0),
                frameSize=self.TabViewport,
                canvasSize=(
                    self.TabViewport[0],
                    self.TabViewport[1] - 0.08,
                    self.TabContentBottoms[tab],
                    self.TabViewport[3],
                ),
                manageScrollBars=1,
                autoHideScrollBars=1,
                scrollBarWidth=0.045,
                borderWidth=(0.008, 0.008),
                verticalScroll_frameColor=(0.13, 0.68, 0.94, 1),
                verticalScroll_thumb_frameColor=(1.0, 0.92, 0.0, 1),
                verticalScroll_thumb_relief=DGG.RAISED,
                verticalScroll_incButton_frameColor=(1.0, 0.92, 0.0, 1),
                verticalScroll_decButton_frameColor=(1.0, 0.92, 0.0, 1),
                pos=(0, 0, 0),
            )
            self.tabCanvases[tab] = self.tabFrames[tab].getCanvas()
            self.tabFrames[tab].hide()

        self.gameplayFrame = self.tabCanvases[self.GameplayTab]
        self.controlsFrame = self.tabCanvases[self.ControlsTab]
        self.audioFrame = self.tabCanvases[self.AudioTab]
        self.videoFrame = self.tabCanvases[self.VideoTab]

        self.__loadGameplay(buttonImages)
        self.__loadControls(buttonImages)
        self.__loadAudio(buttonImages)
        self.__loadVideo(buttonImages)
        guiButton.removeNode()

    def __loadGameplay(self, buttonImages):
        self.experimentalSectionTitle = DirectLabel(
            parent=self.gameplayFrame,
            relief=None,
            text=TTLocalizer.AdvancedSettingsExperimentalSection,
            text_align=TextNode.ALeft,
            text_scale=0.070,
            pos=(-0.62, 0, 0.22),
        )
        self.mouseLookLabel = DirectLabel(
            parent=self.gameplayFrame,
            relief=None,
            text=TTLocalizer.AdvancedSettingsMouseLook,
            text_align=TextNode.ALeft,
            text_scale=0.055,
            pos=(-0.56, 0, 0.05),
        )
        self.mouseLookToggleButton = DirectButton(
            parent=self.gameplayFrame,
            relief=None,
            image=buttonImages,
            image_scale=(0.72, 1, 0.84),
            text='',
            text_scale=0.047,
            text_pos=(0, -0.018),
            pos=(0.42, 0, 0.05),
            command=self.__toggleMouseLook,
        )
        self.mouseLookDescription = DirectLabel(
            parent=self.gameplayFrame,
            relief=None,
            text=TTLocalizer.AdvancedSettingsMouseLookDescription,
            text_align=TextNode.ALeft,
            text_scale=0.040,
            text_wordwrap=32,
            pos=(-0.56, 0, -0.08),
        )
        self.freeCameraLabel = DirectLabel(
            parent=self.gameplayFrame,
            relief=None,
            text=TTLocalizer.AdvancedSettingsFreeCamera,
            text_align=TextNode.ALeft,
            text_scale=0.055,
            pos=(-0.56, 0, -0.29),
        )
        self.freeCameraDescription = DirectLabel(
            parent=self.gameplayFrame,
            relief=None,
            text=TTLocalizer.AdvancedSettingsFreeCameraDescription,
            text_align=TextNode.ALeft,
            text_scale=0.040,
            text_wordwrap=32,
            pos=(-0.56, 0, -0.42),
        )

    def __loadControls(self, buttonImages):
        self.instructions = DirectLabel(
            parent=self.controlsFrame,
            relief=None,
            text=TTLocalizer.AdvancedSettingsIntro,
            text_align=TextNode.ACenter,
            text_scale=0.043,
            text_wordwrap=28,
            pos=(0, 0, 0.29),
        )

        rowTop = 0.14
        rowHeight = 0.13
        for index, action in enumerate(KeybindSettings.Actions):
            rowY = rowTop - index * rowHeight
            labelScale = 0.043 if action == 'exitActivity' else 0.052
            self.actionLabels[action] = DirectLabel(
                parent=self.controlsFrame,
                relief=None,
                text=self.ActionLabels[action],
                text_align=TextNode.ALeft,
                text_scale=labelScale,
                pos=(-0.62, 0, rowY),
            )
            self.bindingButtons[action] = DirectButton(
                parent=self.controlsFrame,
                relief=None,
                image=buttonImages,
                image_scale=(0.75, 1, 0.82),
                text='',
                text_scale=0.048,
                text_pos=(0, -0.018),
                pos=(0.40, 0, rowY),
                command=self.__beginCapture,
                extraArgs=[action],
            )

        lastRowY = rowTop - (len(KeybindSettings.Actions) - 1) * rowHeight
        self.statusLabel = DirectLabel(
            parent=self.controlsFrame,
            relief=None,
            text='',
            text_align=TextNode.ACenter,
            text_scale=0.042,
            text_wordwrap=31,
            pos=(0, 0, lastRowY - 0.16),
        )
        self.resetButton = DirectButton(
            parent=self.controlsFrame,
            relief=None,
            image=buttonImages,
            image_scale=(0.95, 1, 0.9),
            text=TTLocalizer.AdvancedSettingsResetDefaults,
            text_scale=0.047,
            text_pos=(0, -0.018),
            pos=(0, 0, lastRowY - 0.26),
            command=self.__resetDefaults,
        )

    def __loadAudio(self, buttonImages):
        rows = (
            ('music', 0.18),
            ('sfx', 0.00),
            ('toonChatSounds', -0.18),
        )
        self.musicLabel = DirectLabel(
            parent=self.audioFrame,
            relief=None,
            text='',
            text_align=TextNode.ALeft,
            text_scale=0.055,
            pos=(-0.56, 0, rows[0][1]),
        )
        self.soundFxLabel = DirectLabel(
            parent=self.audioFrame,
            relief=None,
            text='',
            text_align=TextNode.ALeft,
            text_scale=0.055,
            pos=(-0.56, 0, rows[1][1]),
        )
        self.toonChatSoundsLabel = DirectLabel(
            parent=self.audioFrame,
            relief=None,
            text='',
            text_align=TextNode.ALeft,
            text_scale=0.050,
            pos=(-0.56, 0, rows[2][1]),
        )
        self.musicToggleButton = DirectButton(
            parent=self.audioFrame,
            relief=None,
            image=buttonImages,
            image_scale=(0.72, 1, 0.84),
            text='',
            text_scale=0.047,
            text_pos=(0, -0.018),
            pos=(0.42, 0, rows[0][1]),
            command=self.__toggleMusic,
        )
        self.soundFxToggleButton = DirectButton(
            parent=self.audioFrame,
            relief=None,
            image=buttonImages,
            image_scale=(0.72, 1, 0.84),
            text='',
            text_scale=0.047,
            text_pos=(0, -0.018),
            pos=(0.42, 0, rows[1][1]),
            command=self.__toggleSoundFx,
        )
        self.toonChatSoundsToggleButton = DirectButton(
            parent=self.audioFrame,
            relief=None,
            image=buttonImages,
            image3_color=Vec4(0.5, 0.5, 0.5, 0.5),
            image_scale=(0.68, 1, 0.78),
            text='',
            text3_fg=(0.5, 0.5, 0.5, 0.75),
            text_scale=0.043,
            text_pos=(0, -0.018),
            pos=(0.42, 0, rows[2][1]),
            command=self.__toggleToonChatSounds,
        )

    def __loadVideo(self, buttonImages):
        self.displaySectionTitle = DirectLabel(
            parent=self.videoFrame,
            relief=None,
            text=TTLocalizer.AdvancedSettingsDisplaySection,
            text_align=TextNode.ALeft,
            text_scale=0.070,
            pos=(-0.62, 0, 0.22),
        )
        self.displaySettingsLabel = DirectLabel(
            parent=self.videoFrame,
            relief=None,
            text='',
            text_align=TextNode.ALeft,
            text_scale=0.055,
            text_wordwrap=16,
            pos=(-0.56, 0, 0.06),
        )
        self.displaySettingsButton = DirectButton(
            parent=self.videoFrame,
            relief=None,
            image=buttonImages,
            image3_color=Vec4(0.5, 0.5, 0.5, 0.5),
            image_scale=(0.72, 1, 0.84),
            text=TTLocalizer.OptionsPageChange,
            text3_fg=(0.5, 0.5, 0.5, 0.75),
            text_scale=0.047,
            text_pos=(0, -0.018),
            pos=(0.42, 0, 0.06),
            command=self.__doDisplaySettings,
        )
        self.visualQualitySectionTitle = DirectLabel(
            parent=self.videoFrame,
            relief=None,
            text=TTLocalizer.AdvancedSettingsVisualQualitySection,
            text_align=TextNode.ALeft,
            text_scale=0.070,
            pos=(-0.62, 0, -0.08),
        )
        self.showFpsLabel = DirectLabel(
            parent=self.videoFrame,
            relief=None,
            text=TTLocalizer.AdvancedSettingsShowFps,
            text_align=TextNode.ALeft,
            text_scale=0.055,
            pos=(-0.56, 0, -0.26),
        )
        self.showFpsButton = DirectButton(
            parent=self.videoFrame,
            relief=None,
            image=buttonImages,
            image_scale=(0.72, 1, 0.84),
            text='',
            text_scale=0.047,
            text_pos=(0, -0.018),
            pos=(0.42, 0, -0.26),
            command=self.__toggleShowFps,
        )

    def enter(self):
        taskMgr.remove(self.DisplaySettingsTaskName)
        self.bindings = KeybindSettings.getBindings(base.settings)
        self.__refreshButtons()
        self.__refreshShowFps()
        self.__refreshDisplaySettings()
        self.__refreshAudio()
        self.__refreshMouseLook()
        self.statusLabel['text'] = ''
        self.accept('wheel_up', self.__scrollActiveTab, [-3])
        self.accept('wheel_down', self.__scrollActiveTab, [3])
        localAvatar.chatMgr.fsm.request('otherDialog')
        self.show()
        self.__setTab(self.GameplayTab, updateAnyways=True)

    def exit(self):
        self.__stopCapture()
        self.ignore('wheel_up')
        self.ignore('wheel_down')
        self.hide()
        if self.displaySettingsChanged:
            taskMgr.doMethodLater(
                self.DisplaySettingsDelay,
                self.writeDisplaySettings,
                self.DisplaySettingsTaskName,
            )
        if localAvatar.chatMgr.fsm.getCurrentState().getName() == 'otherDialog':
            localAvatar.chatMgr.fsm.request('mainMenu')

    def unload(self):
        self.__stopCapture()
        self.writeDisplaySettings()
        taskMgr.remove(self.DisplaySettingsTaskName)
        if self.displaySettings is not None:
            self.ignore(self.displaySettings.doneEvent)
            self.displaySettings.unload()
        self.displaySettings = None
        for button in self.tabButtons.values():
            button.destroy()
        for frame in self.tabFrames.values():
            frame.destroy()
        self.tabButtons = {}
        self.tabFrames = {}
        self.tabCanvases = {}
        self.actionLabels = {}
        self.bindingButtons = {}

    def __setTab(self, tab, updateAnyways=False):
        messenger.send('wakeup')
        if tab not in self.tabFrames:
            return
        if self.activeTab == tab and not updateAnyways:
            return
        if self.activeTab == self.ControlsTab:
            self.__stopCapture()
        for tabName in self.Tabs:
            self.tabFrames[tabName].hide()
            self.tabButtons[tabName]['state'] = DGG.NORMAL
        self.activeTab = tab
        self.tabFrames[tab].show()
        self.tabButtons[tab]['state'] = DGG.DISABLED
        if tab == self.GameplayTab:
            self.__refreshMouseLook()
        elif tab == self.ControlsTab:
            self.__refreshButtons()
        elif tab == self.AudioTab:
            self.__refreshAudio()
        elif tab == self.VideoTab:
            self.__refreshShowFps()
            self.__refreshDisplaySettings()
        self.notify.info('ADVANCED TAB: %s' % tab.upper())

    def __scrollActiveTab(self, steps):
        frame = self.tabFrames.get(self.activeTab)
        if frame is not None and not frame.verticalScroll.isHidden():
            frame.verticalScroll.scrollStep(steps)

    def __toggleShowFps(self):
        messenger.send('wakeup')
        enabled = not bool(base.frameRateMeter)
        base.setFrameRateMeter(enabled)
        base.settings.updateSetting('show-fps', enabled)
        base.settings.writeSettings()
        self.__refreshShowFps()
        self.notify.info('SHOW FPS: %s' % ('ON' if enabled else 'OFF'))

    def __refreshShowFps(self):
        if base.frameRateMeter:
            self.showFpsButton['text'] = TTLocalizer.OptionsPageToggleOff
        else:
            self.showFpsButton['text'] = TTLocalizer.OptionsPageToggleOn

    def __toggleMouseLook(self):
        messenger.send('wakeup')
        enabled = not bool(base.settings.getSetting(
            'experimental-mouse-look', False))
        base.settings.updateSetting('experimental-mouse-look', enabled)
        base.settings.writeSettings()
        avatar = getattr(base, 'localAvatar', None)
        if avatar is not None and hasattr(
            avatar, 'setExperimentalMouseLookEnabled'):
            avatar.setExperimentalMouseLookEnabled(enabled)
        self.__refreshMouseLook()
        self.notify.info(
            'EXPERIMENTAL MOUSE LOOK: %s' % ('ON' if enabled else 'OFF'))

    def __refreshMouseLook(self):
        enabled = bool(base.settings.getSetting(
            'experimental-mouse-look', False))
        self.mouseLookToggleButton['text'] = (
            TTLocalizer.OptionsPageToggleOff
            if enabled else TTLocalizer.OptionsPageToggleOn
        )

    def __toggleMusic(self):
        messenger.send('wakeup')
        enabled = not bool(base.musicActive)
        base.enableMusic(enabled)
        base.settings.updateSetting('music', enabled)
        base.settings.writeSettings()
        self.__refreshAudio()

    def __toggleSoundFx(self):
        messenger.send('wakeup')
        enabled = not bool(base.sfxActive)
        base.enableSoundEffects(enabled)
        base.settings.updateSetting('sfx', enabled)
        base.settings.writeSettings()
        self.__refreshAudio()

    def __toggleToonChatSounds(self):
        messenger.send('wakeup')
        base.toonChatSounds = not bool(base.toonChatSounds)
        base.settings.updateSetting(
            'toon-chat-sounds',
            bool(base.toonChatSounds),
        )
        base.settings.writeSettings()
        self.__refreshAudio()

    def __refreshAudio(self):
        if base.musicActive:
            self.musicLabel['text'] = TTLocalizer.OptionsPageMusicOnLabel
            self.musicToggleButton['text'] = TTLocalizer.OptionsPageToggleOff
        else:
            self.musicLabel['text'] = TTLocalizer.OptionsPageMusicOffLabel
            self.musicToggleButton['text'] = TTLocalizer.OptionsPageToggleOn

        if base.sfxActive:
            self.soundFxLabel['text'] = TTLocalizer.OptionsPageSFXOnLabel
            self.soundFxToggleButton['text'] = TTLocalizer.OptionsPageToggleOff
        else:
            self.soundFxLabel['text'] = TTLocalizer.OptionsPageSFXOffLabel
            self.soundFxToggleButton['text'] = TTLocalizer.OptionsPageToggleOn

        if base.toonChatSounds:
            self.toonChatSoundsLabel['text'] = (
                TTLocalizer.OptionsPageToonChatSoundsOnLabel
            )
            self.toonChatSoundsToggleButton['text'] = (
                TTLocalizer.OptionsPageToggleOff
            )
        else:
            self.toonChatSoundsLabel['text'] = (
                TTLocalizer.OptionsPageToonChatSoundsOffLabel
            )
            self.toonChatSoundsToggleButton['text'] = (
                TTLocalizer.OptionsPageToggleOn
            )
        if base.sfxActive:
            self.toonChatSoundsLabel.setColorScale(1.0, 1.0, 1.0, 1.0)
            self.toonChatSoundsToggleButton['state'] = DGG.NORMAL
        else:
            self.toonChatSoundsLabel.setColorScale(0.5, 0.5, 0.5, 0.5)
            self.toonChatSoundsToggleButton['state'] = DGG.DISABLED

    def __doDisplaySettings(self):
        messenger.send('wakeup')
        if self.displaySettings is None:
            self.displaySettings = DisplaySettingsDialog.DisplaySettingsDialog()
            self.displaySettings.load()
            self.accept(
                self.displaySettings.doneEvent,
                self.__doneDisplaySettings,
            )
        self.displaySettings.enter(self.ChangeDisplaySettings, self.ChangeDisplayAPI)
        self.notify.info('DISPLAY SETTINGS OPENED FROM VIDEO')

    def __doneDisplaySettings(self, anyChanged, apiChanged):
        if anyChanged:
            properties = base.win.getProperties()
            self.displaySettingsChanged = 1
            self.displaySettingsSize = (
                properties.getXSize(),
                properties.getYSize(),
            )
            self.displaySettingsFullscreen = properties.getFullscreen()
            self.displaySettingsEmbedded = self.isPropertiesEmbedded(properties)
            self.displaySettingsApi = base.pipe.getInterfaceName()
            self.displaySettingsApiChanged = apiChanged
        self.__refreshDisplaySettings()

    def isPropertiesEmbedded(self, properties):
        return bool(properties.getParentWindow())

    def __refreshDisplaySettings(self):
        properties = base.win.getProperties()
        if properties.getFullscreen():
            screensize = '%s x %s' % (
                properties.getXSize(),
                properties.getYSize(),
            )
        else:
            screensize = TTLocalizer.OptionsPageDisplayWindowed
        if self.isPropertiesEmbedded(properties):
            screensize = TTLocalizer.OptionsPageDisplayEmbedded
        settings = {
            'screensize': screensize,
            'api': base.pipe.getInterfaceName(),
        }
        if self.ChangeDisplayAPI:
            text = TTLocalizer.OptionsPageDisplaySettings % settings
        else:
            text = TTLocalizer.OptionsPageDisplaySettingsNoApi % settings
        self.displaySettingsLabel['text'] = text

    def writeDisplaySettings(self, task=None):
        if not self.displaySettingsChanged:
            return
        taskMgr.remove(self.DisplaySettingsTaskName)
        self.notify.info(
            'writing new display settings %s, fullscreen %s, embedded %s, '
            '%s to SettingsFile.' % (
                self.displaySettingsSize,
                self.displaySettingsFullscreen,
                self.displaySettingsEmbedded,
                self.displaySettingsApi,
            )
        )
        base.settings.updateSetting(
            'resolution',
            (self.displaySettingsSize[0], self.displaySettingsSize[1]),
        )
        base.settings.updateSetting(
            'windowed-mode',
            not self.displaySettingsFullscreen,
        )
        if self.displaySettingsApiChanged:
            self.notify.warning(
                'Display API changes are not persisted by the browser settings layer.'
            )
        base.settings.writeSettings()
        self.displaySettingsChanged = 0
        return Task.done

    def __refreshButtons(self):
        for action, button in self.bindingButtons.items():
            button['text'] = KeybindSettings.formatBinding(self.bindings[action])

    def __beginCapture(self, action):
        messenger.send('wakeup')
        self.__stopCapture()
        self.captureAction = action
        self.bindingButtons[action]['text'] = TTLocalizer.AdvancedSettingsPressKey
        self.statusLabel['text'] = TTLocalizer.AdvancedSettingsCaptureHint
        self.statusLabel['text_fg'] = (0.2, 0.1, 0, 1)
        self.captureButtons = {
            'arrow_up': KeyboardButton.up(),
            'arrow_down': KeyboardButton.down(),
            'arrow_left': KeyboardButton.left(),
            'arrow_right': KeyboardButton.right(),
            'space': KeyboardButton.asciiKey(b' '),
            'control': KeyboardButton.control(),
            'shift': KeyboardButton.shift(),
            'alt': KeyboardButton.alt(),
            'escape': KeyboardButton.escape(),
            'home': KeyboardButton.home(),
            'end': KeyboardButton.end(),
            'delete': KeyboardButton._del(),
        }
        for button in KeybindSettings.AllowedBindings:
            if len(button) == 1:
                self.captureButtons[button] = KeyboardButton.asciiKey(
                    button.encode('ascii'))
        self.captureButtonsDown = self.__getPressedCaptureButtons()
        if browser_storage is not None:
            try:
                browser_storage.set_item(self.CapturedKeyStorageKey, '')
                self.browserKeyCapture = True
            except RuntimeError:
                self.browserKeyCapture = False
        taskMgr.add(self.__pollCaptureButtons, self.CaptureTaskName)
        self.accept(self.CaptureEvent, self.__captureButtonEvent)

        for buttonThrower in base.buttonThrowers:
            node = buttonThrower.node()
            self.savedButtonThrowers.append((
                node,
                node.getSpecificFlag(),
                node.getButtonDownEvent(),
            ))
            node.setSpecificFlag(False)
            node.setButtonDownEvent(self.CaptureEvent)

    def __stopCapture(self):
        taskMgr.remove(self.CaptureTaskName)
        self.ignore(self.CaptureEvent)
        if self.browserKeyCapture:
            browser_storage.set_item(self.CapturedKeyStorageKey, '')
            self.browserKeyCapture = False
        self.captureButtons = {}
        self.captureButtonsDown = set()
        for node, specificFlag, buttonDownEvent in self.savedButtonThrowers:
            node.setSpecificFlag(specificFlag)
            node.setButtonDownEvent(buttonDownEvent)
        self.savedButtonThrowers = []
        if self.captureAction is not None and hasattr(self, 'bindings'):
            self.bindingButtons[self.captureAction]['text'] = KeybindSettings.formatBinding(
                self.bindings[self.captureAction])
        self.captureAction = None

    def __getPressedCaptureButtons(self):
        return {
            name for name, button in self.captureButtons.items()
            if base.mouseWatcherNode.isButtonDown(button)
        }

    def __captureButtonEvent(self, button):
        for name, captureButton in self.captureButtons.items():
            if button == captureButton:
                self.__captureKey(name)
                return
        self.__captureKey('unsupported')

    def __pollCaptureButtons(self, task):
        if self.browserKeyCapture:
            button = browser_storage.get_item(self.CapturedKeyStorageKey)
            if button:
                browser_storage.set_item(self.CapturedKeyStorageKey, '')
                self.__captureKey(button)
                if self.captureAction is None:
                    return Task.done
                return Task.cont

        pressed = self.__getPressedCaptureButtons()
        newPresses = pressed - self.captureButtonsDown
        self.captureButtonsDown = pressed
        for button in newPresses:
            self.__captureKey(button)
            if self.captureAction is None:
                return Task.done
        return Task.cont

    def __captureKey(self, button):
        action = self.captureAction
        if action is None:
            return
        if button == 'escape':
            self.__stopCapture()
            self.statusLabel['text'] = TTLocalizer.AdvancedSettingsCaptureCancelled
            return
        if button not in KeybindSettings.AllowedBindings:
            self.statusLabel['text'] = TTLocalizer.AdvancedSettingsUnsupportedKey
            self.statusLabel['text_fg'] = (0.8, 0.1, 0.1, 1)
            return

        for otherAction, otherButton in self.bindings.items():
            if otherAction != action and otherButton == button:
                self.statusLabel['text'] = TTLocalizer.AdvancedSettingsDuplicateKey % {
                    'key': KeybindSettings.formatBinding(button),
                    'action': self.ActionLabels[otherAction],
                }
                self.statusLabel['text_fg'] = (0.8, 0.1, 0.1, 1)
                return

        self.bindings[action] = button
        self.bindings = KeybindSettings.saveBindings(base.settings, self.bindings)
        self.__stopCapture()
        self.__refreshButtons()
        self.__reloadControls()
        self.statusLabel['text'] = TTLocalizer.AdvancedSettingsSaved % {
            'action': self.ActionLabels[action],
            'key': KeybindSettings.formatBinding(button),
        }
        self.statusLabel['text_fg'] = (0.05, 0.45, 0.08, 1)

    def __resetDefaults(self):
        self.__stopCapture()
        self.bindings = KeybindSettings.saveBindings(
            base.settings,
            dict(KeybindSettings.DefaultBindings),
        )
        self.__refreshButtons()
        self.__reloadControls()
        self.statusLabel['text'] = TTLocalizer.AdvancedSettingsDefaultsRestored
        self.statusLabel['text_fg'] = (0.05, 0.45, 0.08, 1)

    def __reloadControls(self):
        avatar = getattr(base, 'localAvatar', None)
        manager = getattr(avatar, 'controlManager', None)
        if manager is not None and hasattr(manager, 'reloadKeybindings'):
            manager.reloadKeybindings()
        if avatar is None:
            return
        for pageName in ('invPage', 'questPage', 'questMap'):
            page = getattr(avatar, pageName, None)
            if page is not None and hasattr(page, 'acceptOnscreenHooks'):
                page.acceptOnscreenHooks()
        book = getattr(avatar, 'book', None)
        if book is not None and hasattr(book, 'reloadKeybindings'):
            book.reloadKeybindings()
        if hasattr(avatar, 'reloadPerformActionHotkey'):
            avatar.reloadPerformActionHotkey()


class CodesTabPage(DirectFrame):
    notify = DirectNotifyGlobal.directNotify.newCategory('CodesTabPage')

    def __init__(self, parent = aspect2d):
        self._parent = parent
        DirectFrame.__init__(self, parent=self._parent, relief=None, pos=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0))
        self.load()
        return

    def destroy(self):
        self._parent = None
        DirectFrame.destroy(self)
        return

    def load(self):
        cdrGui = loader.loadModel('phase_3.5/models/gui/tt_m_gui_sbk_codeRedemptionGui')
        instructionGui = cdrGui.find('**/tt_t_gui_sbk_cdrPresent')
        flippyGui = cdrGui.find('**/tt_t_gui_sbk_cdrFlippy')
        codeBoxGui = cdrGui.find('**/tt_t_gui_sbk_cdrCodeBox')
        self.resultPanelSuccessGui = cdrGui.find('**/tt_t_gui_sbk_cdrResultPanel_success')
        self.resultPanelFailureGui = cdrGui.find('**/tt_t_gui_sbk_cdrResultPanel_failure')
        self.resultPanelErrorGui = cdrGui.find('**/tt_t_gui_sbk_cdrResultPanel_error')
        self.successSfx = base.loader.loadSfx('phase_3.5/audio/sfx/tt_s_gui_sbk_cdrSuccess.ogg')
        self.failureSfx = base.loader.loadSfx('phase_3.5/audio/sfx/tt_s_gui_sbk_cdrFailure.ogg')
        self.instructionPanel = DirectFrame(parent=self, relief=None, image=instructionGui, image_scale=0.8, text=TTLocalizer.CdrInstructions, text_pos=TTLocalizer.OPCodesInstructionPanelTextPos, text_align=TextNode.ACenter, text_scale=TTLocalizer.OPCodesResultPanelTextScale, text_wordwrap=TTLocalizer.OPCodesInstructionPanelTextWordWrap, pos=(-0.429, 0, -0.05))
        self.codeBox = DirectFrame(parent=self, relief=None, image=codeBoxGui, pos=(0.433, 0, 0.35))
        self.flippyFrame = DirectFrame(parent=self, relief=None, image=flippyGui, pos=(0.44, 0, -0.353))
        self.codeInput = DirectEntry(parent=self.codeBox, relief=DGG.GROOVE, scale=0.08, pos=(-0.33, 0, -0.006), borderWidth=(0.05, 0.05), frameColor=((1, 1, 1, 1), (1, 1, 1, 1), (0.5, 0.5, 0.5, 0.5)), state=DGG.NORMAL, text_align=TextNode.ALeft, text_scale=TTLocalizer.OPCodesInputTextScale, width=10.5, numLines=1, focus=1, backgroundFocus=0, cursorKeys=1, text_fg=(0, 0, 0, 1), suppressMouse=1, autoCapitalize=0, command=self.__submitCode)
        submitButtonGui = loader.loadModel('phase_3/models/gui/quit_button')
        self.submitButton = DirectButton(parent=self, relief=None, image=(submitButtonGui.find('**/QuitBtn_UP'),
         submitButtonGui.find('**/QuitBtn_DN'),
         submitButtonGui.find('**/QuitBtn_RLVR'),
         submitButtonGui.find('**/QuitBtn_UP')), image3_color=Vec4(0.5, 0.5, 0.5, 0.5), image_scale=1.15, state=DGG.NORMAL, text=TTLocalizer.NameShopSubmitButton, text_scale=TTLocalizer.OPCodesSubmitTextScale, text_align=TextNode.ACenter, text_pos=TTLocalizer.OPCodesSubmitTextPos, text3_fg=(0.5, 0.5, 0.5, 0.75), textMayChange=0, pos=(0.45, 0.0, 0.0896), command=self.__submitCode)
        self.resultPanel = DirectFrame(parent=self, relief=None, image=self.resultPanelSuccessGui, text='', text_pos=TTLocalizer.OPCodesResultPanelTextPos, text_align=TextNode.ACenter, text_scale=TTLocalizer.OPCodesResultPanelTextScale, text_wordwrap=TTLocalizer.OPCodesResultPanelTextWordWrap, pos=(-0.42, 0, -0.0567))
        self.resultPanel.hide()
        closeButtonGui = loader.loadModel('phase_3/models/gui/dialog_box_buttons_gui')
        self.closeButton = DirectButton(parent=self.resultPanel, pos=(0.296, 0, -0.466), relief=None, state=DGG.NORMAL, image=(closeButtonGui.find('**/CloseBtn_UP'), closeButtonGui.find('**/CloseBtn_DN'), closeButtonGui.find('**/CloseBtn_Rllvr')), image_scale=(1, 1, 1), command=self.__hideResultPanel)
        closeButtonGui.removeNode()
        cdrGui.removeNode()
        submitButtonGui.removeNode()
        return

    def enter(self):
        self.show()
        localAvatar.chatMgr.fsm.request('otherDialog')
        self.codeInput['focus'] = 1
        self.codeInput.enterText('')
        self.__enableCodeEntry()

    def exit(self):
        self.resultPanel.hide()
        self.hide()
        localAvatar.chatMgr.fsm.request('mainMenu')

    def unload(self):
        self.instructionPanel.destroy()
        self.instructionPanel = None
        self.codeBox.destroy()
        self.codeBox = None
        self.flippyFrame.destroy()
        self.flippyFrame = None
        self.codeInput.destroy()
        self.codeInput = None
        self.submitButton.destroy()
        self.submitButton = None
        self.resultPanel.destroy()
        self.resultPanel = None
        self.closeButton.destroy()
        self.closeButton = None
        del self.successSfx
        del self.failureSfx
        return

    def __submitCode(self, input = None):
        if input == None:
            input = self.codeInput.get()
        self.codeInput['focus'] = 1
        if input == '':
            return
        messenger.send('wakeup')
        if hasattr(base, 'codeRedemptionMgr'):
            base.codeRedemptionMgr.redeemCode(input, self.__getCodeResult)
        self.codeInput.enterText('')
        self.__disableCodeEntry()
        return

    def __getCodeResult(self, result, awardMgrResult):
        self.notify.debug('result = %s' % result)
        self.notify.debug('awardMgrResult = %s' % awardMgrResult)
        self.__enableCodeEntry()
        if result == 0:
            self.resultPanel['image'] = self.resultPanelSuccessGui
            self.resultPanel['text'] = TTLocalizer.CdrResultSuccess
        elif result == 1 or result == 3:
            self.resultPanel['image'] = self.resultPanelFailureGui
            self.resultPanel['text'] = TTLocalizer.CdrResultInvalidCode
        elif result == 2:
            self.resultPanel['image'] = self.resultPanelFailureGui
            self.resultPanel['text'] = TTLocalizer.CdrResultExpiredCode
        elif result == 4:
            self.resultPanel['image'] = self.resultPanelErrorGui
            if awardMgrResult == 0:
                self.resultPanel['text'] = TTLocalizer.CdrResultSuccess
            elif awardMgrResult == 1 or awardMgrResult == 2 or awardMgrResult == 15 or awardMgrResult == 16:
                self.resultPanel['text'] = TTLocalizer.CdrResultUnknownError
            elif awardMgrResult == 3 or awardMgrResult == 4:
                self.resultPanel['text'] = TTLocalizer.CdrResultMailboxFull
            elif awardMgrResult == 5 or awardMgrResult == 10:
                self.resultPanel['text'] = TTLocalizer.CdrResultAlreadyInMailbox
            elif awardMgrResult == 6 or awardMgrResult == 7 or awardMgrResult == 11:
                self.resultPanel['text'] = TTLocalizer.CdrResultAlreadyInQueue
            elif awardMgrResult == 8:
                self.resultPanel['text'] = TTLocalizer.CdrResultAlreadyInCloset
            elif awardMgrResult == 9:
                self.resultPanel['text'] = TTLocalizer.CdrResultAlreadyBeingWorn
            elif awardMgrResult == 12 or awardMgrResult == 13 or awardMgrResult == 14:
                self.resultPanel['text'] = TTLocalizer.CdrResultAlreadyReceived
        elif result == 5:
            self.resultPanel['text'] = TTLocalizer.CdrResultTooManyFails
            self.__disableCodeEntry()
        elif result == 6:
            self.resultPanel['text'] = TTLocalizer.CdrResultServiceUnavailable
            self.__disableCodeEntry()
        if result == 0:
            self.successSfx.play()
        else:
            self.failureSfx.play()
        self.resultPanel.show()

    def __hideResultPanel(self):
        self.resultPanel.hide()

    def __disableCodeEntry(self):
        self.codeInput['state'] = DGG.DISABLED
        self.submitButton['state'] = DGG.DISABLED

    def __enableCodeEntry(self):
        self.codeInput['state'] = DGG.NORMAL
        self.codeInput['focus'] = 1
        self.submitButton['state'] = DGG.NORMAL
