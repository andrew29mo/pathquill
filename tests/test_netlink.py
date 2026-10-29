import unittest
from pathquill.netlink import RouteSocket
class Sock:
    def send(self,data):return len(data)
class DumpTests(unittest.TestCase):
    def test_interrupted_dump_never_valid(self):
        n=object.__new__(RouteSocket);n.socket=Sock()
        n.receive=lambda:[dict(sequence=1,kind=16,flags=0x10,payload='')]
        self.assertFalse(n.synchronize()['valid'])
    def test_error_done_never_valid(self):
        n=object.__new__(RouteSocket);n.socket=Sock()
        n.receive=lambda:[dict(sequence=1,kind=3,flags=0,payload='ffffffff')]
        self.assertFalse(n.synchronize()['valid'])

    def test_overrun_during_dump_never_valid(self):
        n=object.__new__(RouteSocket);n.socket=Sock()
        n.receive=lambda:[dict(sequence=0,kind=4,flags=0,payload='')]
        self.assertFalse(n.synchronize()['valid'])
    def test_sequence_not_reused(self):
        n=object.__new__(RouteSocket);n.socket=Sock();n.sequence=20
        n.receive=lambda:[dict(sequence=n.sequence,kind=3,flags=0,payload='00000000')]
        self.assertTrue(n.synchronize()['valid']);self.assertEqual(n.sequence,23)
        self.assertTrue(n.synchronize()['valid']);self.assertEqual(n.sequence,26)
