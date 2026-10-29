import unittest
from pathquill.state import State
class Backend:
    def __init__(self,items):self.items=iter(items)
    def synchronize(self):return next(self.items)
def result(records=None,notifications=None,valid=True):return dict(valid=valid,records=records or [],notifications=notifications or [])
class StateTests(unittest.TestCase):
    def test_quiet_rounds_converge(self):
        s=State();self.assertTrue(s.rebuild(Backend([result(),result()])));self.assertEqual(s.status,'RECORDING')
    def test_churn_never_publishes(self):
        s=State();self.assertFalse(s.rebuild(Backend([result(notifications=[{}])]*3)));self.assertIsNone(s.view)
    def test_loss_clears_previous_view(self):
        s=State();s.rebuild(Backend([result(),result()]));g=s.generation
        self.assertFalse(s.rebuild(Backend([result(valid=False)]*3)));self.assertIsNone(s.view);self.assertGreater(s.generation,g)

    def test_unsupported_decode_stays_degraded(self):
        s=State();bad=result(records=[dict(kind=99,payload='')])
        self.assertFalse(s.rebuild(Backend([bad]*3)));self.assertIsNone(s.view)
