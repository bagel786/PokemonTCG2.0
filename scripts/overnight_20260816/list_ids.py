import sys

sys.path.insert(0, 'vendor')
from cg.api import all_card_data

wanted = [
    "Marnie's Impidimp", "Marnie's Morgrem", "Marnie's Grimmsnarl ex",
    'Rare Candy', 'Snorunt', 'Froslass', 'Munkidori',
    "Boss's Orders", 'Spikemuth Gym', 'Punk Up', 'Basic {D} Energy',
    "Lillie's Determination", 'Buddy-Buddy Poffin',
    "Team Rocket's Petrel", 'Unfair Stamp', 'Dawn', 'Night Stretcher',
    'Dreepy', 'Drakloak', 'Dragapult ex', 'Duskull', 'Dusclops', 'Dusknoir',
]
for c in all_card_data():
    if c.name in wanted:
        print(c.cardId, c.name)
