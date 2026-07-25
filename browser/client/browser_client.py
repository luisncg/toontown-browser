"""Small real-engine scene used while the full Toontown bootstrap is adapted."""

from math import sin

from panda3d.core import (
    AmbientLight,
    DirectionalLight,
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    LColor,
    loadPrcFileData,
)


loadPrcFileData(
    "browser-startup",
    """
    window-type onscreen
    audio-library-name p3openal_audio
    sync-video false
    show-frame-rate-meter false
    framebuffer-srgb false
    textures-power-2 none
    notify-level warning
    """,
)

from direct.showbase.ShowBase import ShowBase  # noqa: E402


def _make_cube():
    vertices = (
        (-1, -1, -1),
        (1, -1, -1),
        (1, 1, -1),
        (-1, 1, -1),
        (-1, -1, 1),
        (1, -1, 1),
        (1, 1, 1),
        (-1, 1, 1),
    )
    faces = (
        (0, 2, 1), (0, 3, 2),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6),
        (3, 0, 4), (3, 4, 7),
    )

    data = GeomVertexData("browser-cube", GeomVertexFormat.getV3(), Geom.UHStatic)
    writer = GeomVertexWriter(data, "vertex")
    for vertex in vertices:
        writer.addData3(*vertex)

    triangles = GeomTriangles(Geom.UHStatic)
    for triangle in faces:
        triangles.addVertices(*triangle)

    geom = Geom(data)
    geom.addPrimitive(triangles)
    node = GeomNode("browser-cube")
    node.addGeom(geom)
    return node


class BrowserClient(ShowBase):
    def __init__(self):
        super().__init__()
        self.disableMouse()
        self.setBackgroundColor(0.025, 0.055, 0.11, 1)
        self.camera.setPos(0, -8, 1.1)
        self.camera.lookAt(0, 0, 0)

        self.cube = self.render.attachNewNode(_make_cube())
        self.cube.setColor(0.96, 0.64, 0.20, 1)

        ambient = AmbientLight("ambient")
        ambient.setColor(LColor(0.32, 0.39, 0.52, 1))
        ambient_path = self.render.attachNewNode(ambient)
        self.render.setLight(ambient_path)

        key = DirectionalLight("key")
        key.setColor(LColor(1.0, 0.89, 0.70, 1))
        key_path = self.render.attachNewNode(key)
        key_path.setHpr(-35, -45, 0)
        self.render.setLight(key_path)

        self.started_at = self.clock.getRealTime()

    def animate(self):
        elapsed = self.clock.getRealTime() - self.started_at
        self.cube.setHpr(elapsed * 42, 18 + sin(elapsed * 0.8) * 8, elapsed * 9)


client = BrowserClient()


def frame():
    """Advance one Python/Panda3D frame from requestAnimationFrame."""
    client.animate()
    client.taskMgr.step()
