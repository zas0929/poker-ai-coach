"""Dense terminal/deal/player float64 payoffs with legacy read-only mapping access."""
from array import array
from collections.abc import Mapping


class CompactUtilities(Mapping):
    def __init__(self,nodes,deals,players):
        self.slots={id(node):i for i,node in enumerate(n for n in nodes if n.actor==-1)}
        self.deals=deals;self.players=players
        self.data=array('d',[0.])*(len(self.slots)*deals*players)

    def put(self,node,deal,values):
        start=(self.slots[id(node)]*self.deals+deal)*self.players
        self.data[start:start+self.players]=array('d',values)

    def __getitem__(self,key):
        node,deal=key
        if type(deal) is not int or not 0<=deal<self.deals:raise KeyError(key)
        start=(self.slots[node]*self.deals+deal)*self.players
        return tuple(self.data[start:start+self.players])

    def __iter__(self):
        for node in self.slots:
            for deal in range(self.deals):yield (node,deal)

    def __len__(self):return len(self.slots)*self.deals
