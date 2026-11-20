import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_identity import header_identity, IdentityEvidence


class EntryCorroboratedLetters(unittest.TestCase):
    def candidate(self,name='Biastoise',cp=1500,confidence=.95,vocabulary=None):
        return header_identity([dict(text=f'{name} CP{cp}',confidence=confidence)],
            vocabulary or ['Blastoise'],allow_il_confusable=True)

    def sample(self,t,value):
        return dict(t=t,mine=value,theirs=None,source_pts=round(t*30),source_time_base='1/30')

    def verified(self):
        ledger=IdentityEvidence()
        exact=dict(species='Blastoise',cp=1500,method='physical_header_exact_vocabulary')
        ledger.update(self.sample(1,exact));ledger.update(self.sample(1.33,exact))
        return ledger

    def test_unique_single_il_confusion_is_only_a_candidate(self):
        records=[dict(text='Biastoise CP1500',confidence=.95)]
        self.assertIsNone(header_identity(records,['Blastoise']))
        value=self.candidate()
        self.assertEqual((value['species'],value['cp']),('Blastoise',1500))
        self.assertTrue(value['requires_entry_corroboration'])

    def test_ambiguous_vocabulary_and_unrelated_edits_are_rejected(self):
        self.assertIsNone(self.candidate(vocabulary=['Blastoise','Biastolse']))
        for text in ['Blastolse','BLastolse','Blactoise','Biastolse']:
            # Blastolse has one I/l swap and is a candidate, never a fact.
            if text in ('Blastolse','BLastolse'):
                self.assertTrue(self.candidate(text)['requires_entry_corroboration'])
            else:
                self.assertIsNone(self.candidate(text))

    def test_confidence_floor_and_exact_cp_are_not_relaxed(self):
        self.assertIsNone(self.candidate(confidence=.89))
        self.assertIsNone(header_identity([dict(text='Biastoise CPl500',confidence=.99)],
            ['Blastoise'],allow_il_confusable=True))

    def test_two_candidates_matching_entry_and_already_verified_pair_confirm_return(self):
        ledger=self.verified();value=self.candidate();ann=[dict(t=20,species='Blastoise')]
        self.assertEqual(ledger.update(self.sample(20.1,value),ann),{})
        result=ledger.update(self.sample(20.43,value),ann)
        self.assertEqual(result['mine']['cp'],1500)
        self.assertEqual(result['mine']['confirmed_seconds'],20.43)

    def test_repetition_without_entry_does_not_confirm_systematic_typo(self):
        ledger=self.verified()
        for t in (20,20.33,20.66,21):
            self.assertEqual(ledger.update(self.sample(t,self.candidate())),{})

    def test_entry_cannot_establish_previously_unverified_cp(self):
        for ledger,cp in [(IdentityEvidence(),1500),(self.verified(),1499)]:
            for t in (20.1,20.43,20.76):
                self.assertEqual(ledger.update(self.sample(t,self.candidate(cp=cp)),
                    [dict(t=20,species='Blastoise')]),{})

    def test_future_old_and_different_entry_are_not_corroboration(self):
        for entry in [dict(t=22,species='Blastoise'),dict(t=17,species='Blastoise'),dict(t=20,species='Lapras')]:
            ledger=self.verified()
            for t in (20.1,20.43,20.76):
                self.assertEqual(ledger.update(self.sample(t,self.candidate()),[entry]),{})

    def test_a_candidate_is_not_counted_as_an_independent_exact_header(self):
        ledger=IdentityEvidence()
        ledger.update(self.sample(20,self.candidate()))
        exact=dict(species='Blastoise',cp=1500,method='physical_header_exact_vocabulary')
        self.assertEqual(ledger.update(self.sample(20.33,exact)),{})
        self.assertIn('mine',ledger.update(self.sample(20.66,exact)))
