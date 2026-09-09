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
  // Published SHA-256 vectors plus the two-block padding boundary. The runner
  // uses its own hash implementation for artifact identity.
  assert(runner::sha256("")=="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  assert(runner::sha256("abc")=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  assert(runner::sha256("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")==
    "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
  assert(runner::sha256(std::string(1000000,'a'))=="cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
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
  // Every checkpoint is immutable, includes the run tuple, and advances only
  // after the new final name has been published.
  finished=false;
  std::filesystem::create_directories(job.dir(runner::SDROOT)+"/artifacts");
  runner_checkpoint({{"phase","sample"}});
  const auto first=job.dir(runner::SDROOT)+"/artifacts/progress-0001.kv";
  const auto first_bytes=runner::read(first);
  auto snapshot=runner::parse(first_bytes);
  assert(snapshot.at("run_id")==job.id&&snapshot.at("manifest_sha256")==job.manifestSha);
  assert(snapshot.at("snapshot_complete")=="1"&&snapshot.at("checkpoint_sequence")=="1");
  runner_checkpoint({{"phase","stress"}});
  assert(checkpoint_sequence==2&&runner::read(first)==first_bytes);
  bool duplicate=false;try{runner::atomicWriteNew(first,"replace");}catch(const std::exception& e){
    duplicate=std::string(e.what()).find("stage=destination_exists")!=std::string::npos;
  }
  assert(duplicate&&runner::read(first)==first_bytes);
  checkpoint_sequence=0;
  bool duplicate_checkpoint=false;try{runner_checkpoint({{"phase","duplicate"}});}catch(const std::exception& e){
    duplicate_checkpoint=std::string(e.what()).find("stage=destination_exists")!=std::string::npos;
  }
  assert(duplicate_checkpoint&&checkpoint_sequence==0&&runner::read(first)==first_bytes);
  for(const auto* stage:{"write","flush","fsync","close","rename"}){
    job.id=std::string("test-fault-")+stage;checkpoint_sequence=0;
    std::filesystem::create_directories(job.dir(runner::SDROOT)+"/artifacts");
    runner_checkpoint({{"phase","first"}});
    const auto prior=job.dir(runner::SDROOT)+"/artifacts/progress-0001.kv";
    const auto prior_bytes=runner::read(prior);
    const auto next=job.dir(runner::SDROOT)+"/artifacts/progress-0002.kv";
    runner::atomicWriteFaultStage=stage;
    bool failed=false;try{runner_checkpoint({{"phase","second"}});}catch(const std::exception& e){
      auto message=std::string(e.what());failed=message.find(std::string("stage=")+stage)!=std::string::npos&&
        message.find("errno="+std::to_string(EIO))!=std::string::npos;
    }
    runner::atomicWriteFaultStage=nullptr;
    assert(failed&&checkpoint_sequence==1&&runner::read(prior)==prior_bytes);
    assert(!runner::exists(next)&&runner::exists(next+".tmp"));
    const auto temp_bytes=runner::read(next+".tmp");
    bool retry=false;try{runner_checkpoint({{"phase","retry"}});}catch(const std::exception& e){
      retry=std::string(e.what()).find("stage=open_temporary")!=std::string::npos;
    }
    assert(retry&&checkpoint_sequence==1&&runner::read(next+".tmp")==temp_bytes);
  }
  job.id="test-budget";checkpoint_sequence=0;
  std::filesystem::create_directories(job.dir(runner::SDROOT)+"/artifacts");
  for(int i=0;i<48;++i)runner_checkpoint({{"phase","sample"}});
  bool capped=false;try{runner_checkpoint({});}catch(const std::exception& e){capped=std::string(e.what())=="checkpoint_count_limit";}
  assert(capped&&checkpoint_sequence==48);
  assert(std::distance(std::filesystem::directory_iterator(job.dir(runner::SDROOT)+"/artifacts"),std::filesystem::directory_iterator{})==48);
  job.id="test-size";checkpoint_sequence=0;
  std::filesystem::create_directories(job.dir(runner::SDROOT)+"/artifacts");
  bool oversized=false;try{runner_checkpoint({{"payload",std::string(16384,'x')}});}catch(const std::exception&){oversized=true;}
  assert(oversized&&checkpoint_sequence==0&&std::filesystem::is_empty(job.dir(runner::SDROOT)+"/artifacts"));
  bool identity=false;try{runner_checkpoint({{"run_id","wrong"}});}catch(const std::exception&){identity=true;}
  assert(identity&&checkpoint_sequence==0);
}
''')
            native=ROOT/'src/3ds/runner'
            subprocess.run(['c++','-std=c++17','-DCTH3DS_STUB_BUILD','-DCTH3DS_RUNNER_FAULT_TEST','-I'+str(native),
                str(source),str(native/'core.cpp'),str(native/'rosalina.cpp'),'-o',str(work/'probe')],check=True,capture_output=True)
            subprocess.run([str(work/'probe')],cwd=work,check=True,capture_output=True)
