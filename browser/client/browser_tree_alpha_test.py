"""Isolated WebGL scene for legacy binary-alpha tree cards."""

from panda3d.core import LColor, OrthographicLens, loadPrcFileData


loadPrcFileData(
    "browser-tree-alpha-test",
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


class BrowserTreeAlphaTest(ShowBase):
    def __init__(self):
        super().__init__()
        self.disableMouse()
        self.setBackgroundColor(LColor(0.10, 0.72, 0.88, 1.0))

        lens = OrthographicLens()
        lens.setFilmSize(40.0, 32.0)
        lens.setNearFar(1.0, 200.0)
        self.cam.node().setLens(lens)
        self.camera.setPos(0, -60, 14.5)
        self.camera.lookAt(0, 0, 14.5)

        tree_collection = self.loader.loadModel(
            "phase_3.5/models/props/trees"
        )
        self.tree = tree_collection.find("**/prop_tree_large_no_box_ur")
        if self.tree.isEmpty():
            raise RuntimeError("TTC large tree test model is missing")
        self.tree.reparentTo(self.render)


client = BrowserTreeAlphaTest()


def frame():
    client.taskMgr.step()
