"""Isolated WebGL scene for legacy Toontown card-transparency coverage."""

from panda3d.core import LColor, OrthographicLens, loadPrcFileData


loadPrcFileData(
    "browser-alpha-test",
    """
    window-type onscreen
    audio-library-name p3openal_audio
    sync-video false
    framebuffer-srgb false
    textures-power-2 none
    model-path /resources
    default-model-extension .bam
    m-dual false
    m-binary-alpha true
    notify-level warning
    """,
)

from direct.showbase.ShowBase import ShowBase  # noqa: E402


class BrowserAlphaTest(ShowBase):
    def __init__(self):
        super().__init__()
        self.disableMouse()
        self.setBackgroundColor(LColor(0.10, 0.72, 0.88, 1.0))

        lens = OrthographicLens()
        lens.setFilmSize(7.0, 5.0)
        lens.setNearFar(1.0, 100.0)
        self.cam.node().setLens(lens)
        self.camera.setPos(0, -10, 1.5)
        self.camera.lookAt(0, 0, 1.5)

        self.iceCream = self.loader.loadModel(
            "phase_4/models/props/icecream"
        )
        self.iceCream.reparentTo(self.render)


client = BrowserAlphaTest()


def frame():
    client.taskMgr.step()
