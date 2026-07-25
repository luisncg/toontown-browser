from direct.directnotify import DirectNotifyGlobal
from otp.login.LoginBase import LoginBase
from direct.distributed.PyDatagram import PyDatagram
from direct.distributed.MsgTypes import *

class LoginAstronAccount(LoginBase):
    notify = DirectNotifyGlobal.directNotify.newCategory('LoginAstronAccount')

    def __init__(self, cr):
        LoginBase.__init__(self, cr)
        self._helloSent = False
        self._helloComplete = False
        self._loginPending = False
        self._requestMode = 'login'

    def beginConnection(self):
        """Start Astron's version handshake before showing the login screen."""
        self._helloSent = False
        self._helloComplete = False
        self._loginPending = False
        self._requestMode = 'login'
        self.sendHelloMsg()

    def authorize(self, username, password):
        # The developer account backend keys accounts by play token. Desktop
        # launchers normally provide one before the client starts, but the
        # browser login screen is the source of that identity. Keeping each
        # entered account name as its own token also prevents local browser
        # sessions from all colliding on the fallback "dev" account.
        self.cr.playToken = username
        self.cr.password = password
        self._requestMode = 'login'

    def createAccount(self, username, password, data):
        self.authorize(username, password)
        self._requestMode = 'create'

    def sendHelloMsg(self):
        if self._helloSent:
            return
        datagram = PyDatagram()
        datagram.addUint16(CLIENT_HELLO)
        datagram.addUint32(self.cr.hashVal)
        datagram.addString(self.cr.serverVersion)
        self.cr.send(datagram)
        self._helloSent = True

    def sendLoginMsg(self):
        # The browser opens its gateway connection before the user enters an
        # account name.  CLIENT_HELLO must still be the first Astron packet so
        # that the anonymous login screen can remain connected.  Once the user
        # submits the form, continue immediately if that handshake is complete,
        # or let handleHelloResp continue after the response arrives.
        self._loginPending = True
        if not self._helloSent:
            self.sendHelloMsg()
        if self._helloComplete:
            self._requestLogin()

    def handleHelloResp(self):
        if self._helloComplete:
            return
        self._helloComplete = True
        self.cr.startHeartbeat()
        if self._loginPending:
            self._requestLogin()

    def _requestLogin(self):
        if not self._loginPending:
            return
        self._loginPending = False
        requestMode = self._requestMode
        self._requestMode = 'login'
        if requestMode == 'create':
            self.cr.astronLoginManager.handleRequestCreateAccount()
        else:
            self.cr.astronLoginManager.handleRequestLogin()

    def supportsRelogin(self):
        if __debug__:
            return 1
        return 0

    def supportsAuthenticateDelete(self):
        return 0
