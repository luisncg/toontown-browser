from panda3d.core import *
PieToonup = 1
PieToonupNerfed = 2
PieDamageMult = 1.0
PieDamageMultNerfed = 2.0
AttackMult = 1.0
AttackMultNerfed = 0.5
HitCountDamage = 35
HitCountDamageNerfed = 50
BarrelDefs = {8000: {'pos': Point3(15, 23, 0),
        'hpr': Vec3(-45, 0, 0),
        'rewardPerGrab': 50,
        'rewardPerGrabMax': 0},
 8001: {'pos': Point3(15, -23, 0),
        'hpr': Vec3(-135, 0, 0),
        'gagLevel': 3,
        'gagLevelMax': 0,
        'gagTrack': 3,
        'rewardPerGrab': 10,
        'rewardPerGrabMax': 0},
 8002: {'pos': Point3(21, 20, 0),
        'hpr': Vec3(-45, 0, 0),
        'gagLevel': 3,
        'gagLevelMax': 0,
        'gagTrack': 4,
        'rewardPerGrab': 10,
        'rewardPerGrabMax': 0},
 8003: {'pos': Point3(21, -20, 0),
        'hpr': Vec3(-135, 0, 0),
        'gagLevel': 3,
        'gagLevelMax': 0,
        'gagTrack': 5,
        'rewardPerGrab': 10,
        'rewardPerGrabMax': 0}}


def _installServerBarrelTypes():
    # Keep server implementation classes out of the browser import graph.  The
    # AI process still installs the concrete classes before it creates a VP
    # battle, while clients only need the shared positions and reward values.
    from toontown.coghq import DistributedHealBarrelAI
    from toontown.coghq import DistributedGagBarrelAI

    BarrelDefs[8000]['type'] = DistributedHealBarrelAI.DistributedHealBarrelAI
    for entId in (8001, 8002, 8003):
        BarrelDefs[entId]['type'] = DistributedGagBarrelAI.DistributedGagBarrelAI


try:
    _process = game.process
except NameError:
    _process = 'client'
if _process == 'server':
    _installServerBarrelTypes()
del _process

def setBarrelAttr(barrel, entId):
    for defAttr, defValue in BarrelDefs[entId].items():
        setattr(barrel, defAttr, defValue)


BarrelsStartPos = (0, -36, -8)
BarrelsFinalPos = (0, -36, 0)
