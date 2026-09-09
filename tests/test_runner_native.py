"""Protocol identity protection and native entry rejection without a device."""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class RunnerNativeTests(unittest.TestCase):
    def test_reserved_identity_rejected_and_safe_reasons(self):
        with tempfile.TemporaryDirectory() as name:
            work=Path(name)
            source=work/'probe.cpp'
            source.write_text(r'''
#include "adapter.cpp"
#include <cassert>
#include <filesystem>
int main(){
  char player[]="sdmc:/3ds/corsixth/corsixth.3dsx";
  char target[]="sdmc:/3ds/ftpd-runner/runs/test-run-01/program.3dsx";
  char* ordinary[]={player};char* malformed[]={target};
  assert(cth3ds::runner_start(1,ordinary)==0);
  assert(cth3ds::runner_start(1,malformed)==-1);
  using namespace cth3ds;
  job.id="test-run-01";job.sha=job.configSha=job.inputSha=job.manifestSha=std::string(64,'a');
  std::filesystem::create_directories(job.dir(runner::SDROOT));active=true;
  for(const auto* key:{"run_id","artifact_sha256","config_sha256","input_sha256","manifest_sha256","outcome","phase"}){
    bool rejected=false;try{runner_finish("PASS","complete",{{key,"tampered"}});}catch(const std::exception&){rejected=true;}
    assert(rejected&&!runner::exists(job.dir(runner::SDROOT)+"/result.kv"));
  }
  runner_finish("NOT_PROVEN","first\nsecond\rthird",{{"frames","12"}});
  const auto result=runner::parse(runner::read(job.dir(runner::SDROOT)+"/result.kv"));
  assert(result.at("run_id")=="test-run-01"&&result.at("reason")=="first second third");
  assert(result.at("frames")=="12"&&result.at("outcome")=="NOT_PROVEN");
}
''')
            native=ROOT/'src/3ds/runner'
            subprocess.run(['c++','-std=c++17','-DCTH3DS_STUB_BUILD','-I'+str(native),
                str(source),str(native/'core.cpp'),str(native/'rosalina.cpp'),'-o',str(work/'probe')],check=True,capture_output=True)
            subprocess.run([str(work/'probe')],cwd=work,check=True,capture_output=True)
