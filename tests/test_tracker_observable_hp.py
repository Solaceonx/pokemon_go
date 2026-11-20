import unittest
from pogo.gamedata import GameData
from pogo.tracker import Tracker, Observation, state, whole_hp


class ObservableHealthTests(unittest.TestCase):
    def test_positive_fraction_cannot_round_to_a_faint(self):
        self.assertEqual(whole_hp(.001,110),1)
        self.assertEqual(whole_hp(0,110),0)
        self.assertEqual(whole_hp(1,110),110)
        with self.assertRaises(ValueError):whole_hp(float('nan'),110)

    def test_unreadable_initial_team_is_explicitly_empty(self):
        tracker=Tracker(GameData(),[])
        tracker.update(Observation(t=1,foe_species='snorlax'))
        snapshot=state(tracker)
        self.assertIsNone(snapshot['me']['active'])
        self.assertEqual(snapshot['me']['pokemon'],[])
        tracker.update(Observation(t=2,my_species='lanturn',my_hp=.001,foe_species='snorlax',foe_hp=1))
        self.assertEqual(tracker.me.mon.hp,1)
        self.assertEqual(tracker.me.mon.build.species_id,'lanturn')
        self.assertFalse(tracker.my_moves_known[0])


if __name__=='__main__':unittest.main()
