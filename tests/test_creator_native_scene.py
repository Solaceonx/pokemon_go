import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_frames import native_fighting_scene


class NativeSceneTests(unittest.TestCase):
    def test_fresh_sidebars_and_both_buttons_establish_battle_camera(self):
        bars={'mine':{'fraction':.3},'theirs':{'fraction':.8}}
        controls=dict(t=10,controls={'discs':[{'status':'observed'},{'status':'observed'}]})
        self.assertTrue(native_fighting_scene(bars,controls,10.1))
        self.assertFalse(native_fighting_scene(bars,controls,10.4))
        bars['mine']['camera_owner_basis']='charged_target'
        self.assertFalse(native_fighting_scene(bars,controls,10.1))
        bars['mine']=None
        self.assertFalse(native_fighting_scene(bars,controls,10.1))

    def test_header_geometry_can_corroborate_both_bars_without_button_labels(self):
        bars={'mine':{'fraction':.3},'theirs':{'fraction':.8}}
        headers={s:{'panels':[{'bounds':[1,2,3,4]}]} for s in ['mine','theirs']}
        self.assertTrue(native_fighting_scene(bars,None,10,headers))
        headers['theirs']['panels']=[]
        self.assertFalse(native_fighting_scene(bars,None,10,headers))
