"""Observed AWG framing contracts; no arbitrary production default MTU is added."""
import unittest
from awg_pmtu_probe import SIZES,packet,decode,outer_ipv4_sizes,client_mtu_for_ipv4_path

class AwgPMTUContracts(unittest.TestCase):
    def test_prescribed_probe_sizes_and_synthetic_payload_boundaries(self):
        self.assertEqual(SIZES,(64,256,512,1000,1200,1280,1350,1400,1440,1460,2048))
        for size in SIZES:
            data=packet('C',size,2);self.assertEqual(len(data),size);self.assertEqual(decode(data),('C',size,2))
    def test_no_user_payload_is_accepted_as_synthetic_probe(self):
        with self.assertRaises(ValueError):decode(b'notoursC'+b'\x00\x40\x00\x00'+b'private data')
    def test_measured_baseline_encapsulation_lengths(self):
        expected={64:[168],256:[360],512:[616],1000:[1112],1200:[1304],1280:[1384],1350:[1464],1400:[1492,104],1440:[1492,152],1460:[1492,168],2048:[1492,760]}
        for payload,lengths in expected.items():self.assertEqual(outer_ipv4_sizes(payload,1420),lengths)
    def test_inner_unfragmented_datagram_can_still_exceed_outer_path(self):
        self.assertLess(1350+28,1420);self.assertEqual(outer_ipv4_sizes(1350,1420),[1464]);self.assertGreater(1464,1440)
    def test_measured_pmtu_and_s4_derive_client_only_mtu(self):
        self.assertEqual(client_mtu_for_ipv4_path(1440,12),1368)
        for payload in SIZES:self.assertLessEqual(max(outer_ipv4_sizes(payload,1368)),1440)
        self.assertEqual(outer_ipv4_sizes(2048,1368),[1440,808])
    def test_s4_changes_are_included_not_assumed_zero(self):
        self.assertEqual(client_mtu_for_ipv4_path(1440,0),1380);self.assertEqual(client_mtu_for_ipv4_path(1440,28),1352)
    def test_invalid_bounds_are_refused(self):
        for args in [(-1,1420),(65508,1420),(64,0)]:
            with self.assertRaises(ValueError):outer_ipv4_sizes(*args)
        for args in [(100,12),(1440,-1)]:
            with self.assertRaises(ValueError):client_mtu_for_ipv4_path(*args)

if __name__=='__main__':unittest.main()
