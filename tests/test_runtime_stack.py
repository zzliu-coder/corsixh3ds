import unittest
from check_runtime_stack import inspect_frames


class RuntimeStackTests(unittest.TestCase):
    names = ('cth3ds::register_lua_module(lua_State*)',
             'cth3ds::RuntimeObservations::reset(unsigned long long)',
             'cth3ds::RuntimeObservations::flush(int)')

    def fixture(self, sizes=(64, 32, 1488)):
        names = ''.join(f'{0x100000+i*0x100:x} T {n}\n' for i, n in enumerate(self.names))
        frames = '\n\n'.join(f'000 FDE cie=0 pc={0x100000+i*0x100:x}..{0x100080+i*0x100:x}\n'
                               f'  DW_CFA_def_cfa_offset: {size}' for i, size in enumerate(sizes))
        return names, frames

    def test_bounded_frames_pass_and_hidden_r56_temporary_is_rejected(self):
        self.assertEqual(inspect_frames(*self.fixture())['result'], 'PASS')
        report = inspect_frames(*self.fixture((53680, 32, 1488)))
        self.assertEqual(report['result'], 'FAIL')
        self.assertEqual(report['failures'][0]['frame_bytes'], 53680)

    def test_missing_and_unknown_frames_fail_closed(self):
        symbols, frames = self.fixture()
        self.assertEqual(inspect_frames(symbols, '')['result'], 'FAIL')
        self.assertEqual(inspect_frames(symbols, frames + '\nDW_CFA_def_cfa_expression: unknown')['result'], 'FAIL')
        self.assertEqual(inspect_frames(symbols + '110000 T cth3ds::uncovered()\n', frames)['result'], 'FAIL')

    def test_non_observer_port_frames_are_also_checked(self):
        symbols, frames = self.fixture()
        symbols += '110000 T cth3ds::hash_file()\n'
        frames += '\n\n000 FDE cie=0 pc=110000..110100\nDW_CFA_def_cfa_offset: 66088'
        report = inspect_frames(symbols, frames)
        self.assertEqual(report['result'], 'FAIL')
        self.assertEqual(report['failures'][0]['symbol'], 'cth3ds::hash_file()')
