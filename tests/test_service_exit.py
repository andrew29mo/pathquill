import unittest
from pathquill.service_exit import receipt
class ServiceExitTests(unittest.TestCase):
    def test_systemd_exit_status_is_preserved(self):
        value=receipt(dict(SERVICE_RESULT='success',EXIT_CODE='exited',EXIT_STATUS='78',INVOCATION_ID='12345678123412341234123456789abc'))
        self.assertEqual(value,dict(schema='pathquill-service-exit-v1',result='success',code='exited',status='78',invocation='12345678123412341234123456789abc'))
    def test_receipt_does_not_dump_arbitrary_environment_values(self):
        value=receipt(dict(SERVICE_RESULT='PRIVATE',EXIT_CODE='PRIVATE',EXIT_STATUS='/private/path',INVOCATION_ID='PRIVATE',TOKEN='SECRET'))
        self.assertEqual(value['result'],'unknown');self.assertEqual(value['code'],'unknown');self.assertEqual(value['status'],'unknown');self.assertIsNone(value['invocation'])
        self.assertNotIn('PRIVATE',str(value));self.assertNotIn('SECRET',str(value))
