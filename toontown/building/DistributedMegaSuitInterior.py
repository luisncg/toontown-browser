from . import DistributedSuitInterior


class DistributedMegaSuitInterior(
        DistributedSuitInterior.DistributedSuitInterior):
    """Client view for an all-Mega, up-to-eight-Toon building run."""

    def __init__(self, cr):
        DistributedSuitInterior.DistributedSuitInterior.__init__(self, cr)
        self.squads = [[], []]

    def setSquads(self, firstSquad, secondSquad):
        self.squads = [list(firstSquad), list(secondSquad)]

    def getSquads(self):
        return self.squads

    def setSuits(self, suitIds, reserveIds, values):
        """Mirror the parent without its one-global-reserve cutscene.

        Each Mega battle front owns and animates its own reinforcements.  A
        global interior transition here would interrupt the other front and
        steal its camera.
        """
        oldSuits = self.suits
        self.suits = []
        self.joiningReserves = []
        for suitId in suitIds:
            if suitId in self.cr.doId2do:
                suit = self.cr.doId2do[suitId]
                self.suits.append(suit)
                suit.fsm.request('Battle')
                suit.buildingSuit = 1
                suit.reparentTo(render)
            else:
                self.notify.warning('setSuits() - no suit: %d' % suitId)

        self.reserveSuits = []
        for index in range(len(reserveIds)):
            suitId = reserveIds[index]
            if suitId in self.cr.doId2do:
                suit = self.cr.doId2do[suitId]
                self.reserveSuits.append((suit, values[index]))
            else:
                self.notify.warning('setSuits() - no suit: %d' % suitId)

        # Keep references to newly seen Cogs alive, but leave movement and
        # camera work to their DistributedBattleBldg instance.
        for suit in self.suits:
            if suit not in oldSuits:
                suit.loop('neutral')
