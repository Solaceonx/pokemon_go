import unittest
from segment_battles import propose_segments,evaluate_segments
from extract_battles import validate_candidate


def sample(t,hud=True,party=(3,3),shields=4,digit=None,**extra):
    return {"t":t,"hud":hud,"cp":[1492,1499] if hud else [None,None],
            "party":list(party) if hud else None,"shields_total":shields if hud else None,
            "countdown":{"digit":digit,"confidence":.99} if digit else None,**extra}


class SegmentationTests(unittest.TestCase):
    def facts(self,rows,duration=160):
        return {"samples":rows,"duration_seconds":duration,"sample_interval_seconds":.5}

    def test_countdown_is_grouped_and_result_used(self):
        rows=[sample(0,False,battle_starting=True),sample(2,False,digit=3),sample(2.5,False,digit=2),sample(3,False,digit=1)]
        rows += [sample(t) for t in range(4,45)]
        rows += [sample(45,False,result="win"),sample(46,False,result="win")]
        segments=propose_segments(self.facts(rows),"source")
        self.assertEqual(len(segments),1)
        self.assertEqual((segments[0]["start"],segments[0]["end"]),(0,48))
        self.assertEqual(segments[0]["end_uncertainty_seconds"],2)
        self.assertTrue(segments[0]["review_required"])
        self.assertNotIn("battle_start_seconds",segments[0])

    def test_party_shield_reset_detects_edited_next_battle(self):
        rows=[sample(t) for t in range(40)]
        rows += [sample(t,party=(1,1),shields=0) for t in range(40,60)]
        rows += [sample(t) for t in range(60,110)]
        segments=propose_segments(self.facts(rows),"source")
        self.assertEqual(len(segments),2)
        self.assertEqual(segments[1]["cues"][0]["kind"],"party_and_shields_reset")
        self.assertEqual(segments[1]["start"],60)

    def test_switch_or_animation_does_not_create_battle(self):
        rows=[sample(t,party=(3,3),shields=4) for t in range(30)]
        rows += [sample(t,False) for t in range(30,40)]
        rows += [sample(t,party=(2,3),shields=3) for t in range(40,85)]
        self.assertEqual(len(propose_segments(self.facts(rows),"source")),1)

    def test_one_frame_marker_noise_does_not_reset(self):
        rows=[sample(t) for t in range(80)]
        rows[20]=sample(20,party=(0,0),shields=0)
        self.assertEqual(len(propose_segments(self.facts(rows),"source")),1)

    def test_digit_without_following_hud_does_not_create_clip(self):
        rows=[sample(t,False,digit=2 if t==20 else None) for t in range(40)]
        self.assertEqual(propose_segments(self.facts(rows),"source"),[])

    def test_isolated_attack_streak_digit_does_not_split_battle(self):
        rows=[sample(t) for t in range(100)]
        for t in [22,39,65]:rows[t]=sample(t,digit=1)
        self.assertEqual(len(propose_segments(self.facts(rows),"source")),1)

    def test_last_charged_animation_is_retained_until_next_entry(self):
        rows=[sample(t) for t in range(40)]
        rows += [sample(t,False) for t in range(40,50)]
        rows += [sample(50,False,digit=3),sample(51,False,digit=2),sample(52,False,digit=1)]
        rows += [sample(t) for t in range(53,100)]
        segments=propose_segments(self.facts(rows),"s")
        self.assertEqual(len(segments),2)
        self.assertEqual(segments[0]["end"],segments[1]["start"])
        self.assertGreater(segments[0]["end"],45)
        self.assertEqual(segments[0]["end_method"],"next_battle_entry_edit_or_gap")

    def test_evaluation_reports_miss_and_false_candidate(self):
        predicted=[{"id":"p1","source_id":"s","start":11,"end":39},{"id":"p2","source_id":"s","start":80,"end":100}]
        truth=[{"id":"t1","source_id":"s","start":10,"end":40},{"id":"t2","source_id":"s","start":120,"end":150}]
        score=evaluate_segments(predicted,truth,"s")
        self.assertEqual(score["matched"],1)
        self.assertEqual(score["missed"],["t2"])
        self.assertEqual(score["unmatched_candidates"],["p2"])
        self.assertEqual(score["matches"][0]["start_error_seconds"],1)
        self.assertEqual(score["matches"][0]["end_error_seconds"],-1)

    def test_candidate_paths_and_time_bounds_are_checked(self):
        for candidate in [{"id":"../escape","start":0,"end":1},{"id":"s","start":-1,"end":1},{"id":"s","start":5,"end":4},{"id":"s","start":0,"end":11}]:
            with self.assertRaises(ValueError):
                validate_candidate(candidate,duration=10)


if __name__=="__main__":
    unittest.main()
