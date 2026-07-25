import random
import time

from direct.directnotify import DirectNotifyGlobal
from toontown.estate.EstateTransactionAI import (
    AstronObjectTransaction, chargeBalances)
from toontown.pets import PetDNA, PetMood, PetTraits, PetUtil
from toontown.pets.PetNameGenerator import PetNameGenerator


class PetManagerAI:
    notify = DirectNotifyGlobal.directNotify.newCategory('PetManagerAI')

    def __init__(self, air):
        self.air = air
        self._seedDay = -1
        self._seeds = {}
        self._operations = set()
        self.nameGenerator = None

    def getAvailablePets(self, firstNumPets=3, secondNumPets=2):
        count = max(1, min(32, int(firstNumPets) + int(secondNumPets)))
        day = int(time.time() // 86400)
        if day != self._seedDay:
            self._seedDay = day
            self._seeds = {}
        if count not in self._seeds:
            rng = random.Random((day << 16) ^ int(self.air.districtId or 0))
            self._seeds[count] = rng.sample(range(256), count)
        return list(self._seeds[count])

    def createNewPetFromSeed(self, avId, seed, nameIndex, gender, safeZoneId,
                             cost=0, callback=None):
        if callback is None:
            callback = lambda success, petId: None
        avatar = self.air.doId2do.get(avId)
        if (avatar is None or avId in self._operations or
                avatar.getPetId() != 0):
            callback(False, 0)
            return
        balances = chargeBalances(
            avatar.getMoney(), avatar.getBankMoney(), cost)
        if balances is None:
            callback(False, 0)
            return
        try:
            if self.nameGenerator is None:
                self.nameGenerator = PetNameGenerator()
            petName = self.nameGenerator.getName(int(nameIndex))
            _, dna, traitSeed = PetUtil.getPetInfoFromSeed(
                int(seed), int(safeZoneId))
        except Exception as error:
            self.notify.warning(
                'Could not build pet offer for avatar %s: %s' %
                (avId, error))
            callback(False, 0)
            return
        dna = list(dna)
        dna[PetDNA.Fields['gender']] = int(gender) % len(PetDNA.PetGenders)
        traits = PetTraits.PetTraits(traitSeed, safeZoneId)
        fields = {
            'setOwnerId': avId,
            'setPetName': petName,
            'setTraitSeed': traitSeed,
            'setSafeZone': safeZoneId,
            'setHead': dna[PetDNA.Fields['head']],
            'setEars': dna[PetDNA.Fields['ears']],
            'setNose': dna[PetDNA.Fields['nose']],
            'setTail': dna[PetDNA.Fields['tail']],
            'setBodyTexture': dna[PetDNA.Fields['body']],
            'setColor': dna[PetDNA.Fields['color']],
            'setColorScale': dna[PetDNA.Fields['colorScale']],
            'setEyeColor': dna[PetDNA.Fields['eyes']],
            'setGender': dna[PetDNA.Fields['gender']],
            'setLastSeenTimestamp': int(time.time()),
            'setTrickAptitudes': [],
        }
        for traitName in PetTraits.getTraitNames():
            fields['set%s%s' % (
                traitName[0].upper(), traitName[1:])] = (
                    traits.getTraitValue(traitName))
        for component in PetMood.PetMood.Components:
            fields['set%s%s' % (
                component[0].upper(), component[1:])] = 0.0
        dclass = self.air.dclassesByName['DistributedPetAI']
        self._operations.add(avId)

        def created(petId):
            if not petId:
                self._operations.discard(avId)
                callback(False, 0)
                return
            oldFields = {
                'setPetId': avatar.getPetId(),
                'setMoney': avatar.getMoney(),
                'setBankMoney': avatar.getBankMoney(),
            }
            newFields = {
                'setPetId': petId,
                'setMoney': balances[0],
                'setBankMoney': balances[1],
            }

            def linked(success, conflicts):
                self._operations.discard(avId)
                if not success:
                    # The newly created record is deliberately retained but is
                    # unlinked. We never delete a pre-existing pet when a Toon
                    # record changed concurrently.
                    self.notify.warning(
                        'Pet %s was created but not linked to avatar %s due '
                        'to a Toon transaction conflict' % (petId, avId))
                    callback(False, 0)
                    return
                avatar.setPetId(petId)
                avatar.d_setPetId(petId)
                avatar.setMoney(balances[0])
                avatar.d_setMoney(balances[0])
                avatar.setBankMoney(balances[1])
                avatar.d_setBankMoney(balances[1])
                self.air.writeServerEvent(
                    'bought-pet', avId,
                    'petId=%s cost=%s' % (petId, cost))
                estateManager = getattr(self.air, 'estateMgr', None)
                if estateManager is not None:
                    estateManager.ownerPetIds[avId] = petId
                    estateZone = estateManager.ownerToZone.get(avId)
                    if estateZone and avatar.zoneId == estateZone:
                        estateManager._activateOwnerPet(avId, estateZone)
                callback(True, petId)

            AstronObjectTransaction(
                self.air, avId,
                self.air.dclassesByName['DistributedToonAI']).commit(
                    oldFields, newFields, linked)

        self.air.dbInterface.createObject(
            self.air.dbId, dclass,
            {name: (value,) if not isinstance(value, tuple) else value
             for name, value in fields.items()},
            created)

    def deleteToonsPet(self, avId, callback=None):
        """Unlink a returned pet without destroying its preserved DB record."""
        if callback is None:
            callback = lambda success: None
        avatar = self.air.doId2do.get(avId)
        if avatar is None or avId in self._operations:
            callback(False)
            return
        petId = avatar.getPetId()
        if not petId:
            callback(False)
            return
        self._operations.add(avId)

        def unlinked(success, conflicts):
            self._operations.discard(avId)
            if not success:
                callback(False)
                return
            avatar.setPetId(0)
            avatar.d_setPetId(0)
            pet = self.air.doId2do.get(petId)
            if pet is not None:
                pet.setInactive()
                pet.requestDelete()
            estateManager = getattr(self.air, 'estateMgr', None)
            if estateManager is not None:
                estateManager.ownerPetIds[avId] = 0
                estateManager.pets.pop(avId, None)
            self.air.writeServerEvent(
                'returned-pet', avId, 'petId=%s retained' % petId)
            callback(True)

        AstronObjectTransaction(
            self.air, avId,
            self.air.dclassesByName['DistributedToonAI']).commit(
                {'setPetId': petId}, {'setPetId': 0}, unlinked)
