"""End-to-end browser WebSocket transport check for CConnectionRepository."""

from panda3d.core import Datagram
from panda3d.direct import CConnectionRepository

import browser_client
import browser_storage


repository = CConnectionRepository()
gateway = browser_storage.get_item("open-toontown.game-server")
if not repository.connectWebsocket(gateway):
    raise RuntimeError("Could not create the browser WebSocket")

sent = False
complete = False


def frame():
    global sent, complete

    browser_client.frame()
    if complete:
        return

    if repository.isWebsocketOpen() and not sent:
        repository.sendDatagram(Datagram(b"browser-to-astron"))
        sent = True

    if repository.checkDatagram():
        incoming = Datagram()
        repository.getDatagram(incoming)
        payload = bytes(incoming)
        if not payload:
            raise RuntimeError("Astron returned an empty datagram")
        complete = True
        print(f"[BrowserNetworkTest] roundtrip-ok bytes={len(payload)}")
