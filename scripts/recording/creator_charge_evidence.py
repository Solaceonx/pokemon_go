"""Resolve visible releases from legal vocabulary and already observed cues.

No future roster, assumed moveset or battle outcome supplies an actor or side.
Occurrence time is retained separately from later identity confirmation.
"""
import difflib
import re
from functools import lru_cache
from visible_vocabulary import species_key, move_key


def compact(value):
    return species_key(value).lower()


@lru_cache(maxsize=None)
def actor_for_release(text, move_name, legal_pairs):
    """Exact names outrank fuzzy prefixes; fuzzy names must permit the move."""
    text=compact(text)
    if not text:
        return None
    names={name for name,_ in legal_pairs}
    exact=[name for name in names if compact(name)==text]
    if len(exact)==1:
        return dict(name=exact[0],quality=1.,method='exact_visible_actor')
    if not move_name:
        return None
    legal={name for name,move in legal_pairs if move_key(move)==move_key(move_name)}
    ranked=sorted(((difflib.SequenceMatcher(None,text,compact(name)).ratio(),name)
                   for name in legal),reverse=True)
    if not ranked or ranked[0][0]<.72 or (len(ranked)>1 and ranked[0][0]-ranked[1][0]<.08):
        return None
    score,name=ranked[0]
    return dict(name=name,quality=score,method='legal_move_and_unique_fuzzy_actor')


def actor_consensus(observations):
    """A later exact banner can correct a garbled prefix without backdating knowledge."""
    if not observations:
        return None
    best=max(o['quality'] for o in observations)
    strongest=[o for o in observations if o['quality']==best]
    names={o['name'] for o in strongest}
    if len(names)!=1:
        return None
    first=min(strongest,key=lambda o:o['t'])
    return {**first,'observations':len([o for o in observations if o['name']==first['name']])}


def historical_side(actor, fields, at):
    """An actor on only one currently observed field settles a missing cue.

    This uses physical headers already confirmed by the release, including a
    caught attack. A future entry or a whole-battle species list is insufficient.
    """
    current={}
    for side in ['mine','theirs']:
        prior=[f for f in fields[side] if f.get('seen',float('inf'))<=at]
        current[side]=prior[-1]['name'] if prior else None
    matched=[side for side,name in current.items() if name==actor]
    return matched[0] if len(matched)==1 and all(current.values()) else None


def prior_minigame(texts, after, release):
    """Only this charge's preceding minigame, never an earlier release's cues."""
    candidates=[r['t'] for r in texts if max(after,release-9)<=r['t']<release
        and any(compact(text) in ('nice','great','excellent') for _,text in r['text'])]
    return min(candidates) if candidates else None


def conflicting_incoming_cue(charge, fields, texts, after):
    """Resolve a named own release while preserving the contrary earlier cue.

    Edited playback can jump from an incoming cue to our minigame. Neither the
    cue nor a whole-battle roster may override fresh own charging AND an actor
    already uniquely identified on our field. No exact action-start is inferred.
    """
    announcements = charge.get('announcements', [])
    if charge.get('side') != 'theirs' or not announcements or not charge.get('ours'):
        return None
    release = min(announcements)
    mini = prior_minigame(texts, max(after, charge['start']), release)
    if mini is None or historical_side(charge.get('user'), fields, release) != 'mine':
        return None
    return dict(side='mine', side_evidence='own_minigame_and_past_actor_with_conflicting_cue',
        side_confirmed_clip_seconds=max(release, charge.get('actor_confirmed_clip_seconds') or release),
        cue_conflict=dict(side='theirs', clip_seconds=charge['start'], own_minigame_seconds=mini,
                          status='earlier_incoming_release_unresolved', exact_action_start_verified=False))
