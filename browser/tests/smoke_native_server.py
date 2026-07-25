"""Verify the project-local native Panda3D runtime needed by AI and UberDOG."""

from pathlib import Path

from panda3d.core import HTTPClient
from panda3d.ode import OdeWorld
from panda3d.toontown import DNAStorage, loadDNAFileAI


PROJECT_DIR = Path(__file__).resolve().parents[2]
TUTORIAL_DNA = PROJECT_DIR / "resources/phase_3.5/dna/tutorial_street.dna"

storage = DNAStorage()
loadDNAFileAI(storage, str(TUTORIAL_DNA))
blocks = [
    storage.getBlockNumberAt(index)
    for index in range(storage.getNumBlockNumbers())
]

assert blocks == [1, 2], blocks
assert HTTPClient.getGlobalPtr() is not None
assert OdeWorld() is not None

print(f"Native server smoke passed: tutorial DNA blocks {blocks}, HTTP, and ODE")
