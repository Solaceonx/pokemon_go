"""Whitelisted visible labels, keeping explicit forms and enhanced moves distinct."""
import re


def display_species(name):
    match = re.fullmatch(r'(.+) \(Mega(?: ([XY]))?\)', name)
    if match:
        return 'Mega '+match[1]+(' '+match[2] if match[2] else '')
    return name


def species_key(name):
    # Generic headers do not establish regional forms. Explicit Mega names do.
    label = display_species(name or '')
    return re.sub('[^A-Z]', '', re.sub(r'\([^)]*\)', '', label).upper())


def move_key(name):
    return re.sub('[^A-Z+]', '', (name or '').replace('\uff0b', '+').upper())


def header_species_names(gamemaster):
    return sorted({p['speciesName'] if display_species(p['speciesName']) != p['speciesName']
                   else p['speciesName'].split(' (')[0] for p in gamemaster['pokemon']})


def legal_release_pairs(gamemaster):
    moves = {m['moveId']: m['name'].split(' (')[0] for m in gamemaster['moves']}
    pairs = set()
    for pokemon in gamemaster['pokemon']:
        name = pokemon['speciesName']
        if display_species(name) == name:
            name = name.split(' (')[0]
        for mid in pokemon['chargedMoves']+pokemon.get('extraChargedMoves', []):
            if mid in moves:
                pairs.add((name, moves[mid]))
    return tuple(sorted(pairs))
