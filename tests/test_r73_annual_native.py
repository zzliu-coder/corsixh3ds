"""Annual fields through the actual immutable checkpoint/result writer and parser."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class AnnualNativeTests(unittest.TestCase):
    def test_existing_result_protocol_preserves_optional_annual_fields(self):
        with tempfile.TemporaryDirectory(prefix='annual-native-') as directory:
            work=Path(directory);source=work/'probe.cpp'
            source.write_text(r'''
#include "adapter.cpp"
#include <cassert>
#include <filesystem>
int main(){
 using namespace cth3ds;
 job.id="annual-01";job.sha=job.configSha=job.inputSha=job.manifestSha=std::string(64,'a');
 active=true;std::filesystem::create_directories(job.dir(runner::SDROOT)+"/artifacts");
 runner::Fields fields={{"stress_annual_attempts","1"},{"stress_annual_passes","0"},
 {"stress_annual_failures","0"},{"stress_annual_incomplete","1"},
 {"stress_annual_observation_errors","0"},{"stress_annual_outcome","NOT_PROVEN"}};
 auto checkpoint=fields;checkpoint["annual_event"]="ATTEMPT";
 runner_checkpoint(checkpoint);
 auto first=runner::read(job.dir(runner::SDROOT)+"/artifacts/progress-0001.kv");
 assert(runner::parse(first).at("stress_annual_incomplete")=="1");
 checkpoint["annual_event"]="PASS";checkpoint["stress_annual_passes"]="1";
 checkpoint["stress_annual_incomplete"]="0";
 runner::atomicWriteFaultStage="write";bool failed=false;
 try{runner_checkpoint(checkpoint);}catch(const std::exception&){failed=true;}
 runner::atomicWriteFaultStage=nullptr;
 assert(failed&&checkpoint_sequence==1&&runner::read(job.dir(runner::SDROOT)+"/artifacts/progress-0001.kv")==first);
 assert(!runner::exists(job.dir(runner::SDROOT)+"/artifacts/progress-0002.kv"));
 fields["stress_annual_passes"]="1";fields["stress_annual_incomplete"]="0";
 fields["stress_annual_outcome"]="PASS";fields["stress_annual_observation_errors"]="1";
 runner_finish("FAIL","ANNUAL_OBSERVATION_FAILED",fields);
 auto result=runner::parse(runner::read(job.dir(runner::SDROOT)+"/result.kv"));
 assert(result.at("outcome")=="FAIL"&&result.at("stress_annual_passes")=="1");
 assert(result.at("stress_annual_observation_errors")=="1");
 job.id="annual-result-fail";finished=false;
 std::filesystem::create_directories(job.dir(runner::SDROOT));
 runner::atomicWriteFaultStage="write";failed=false;
 try{runner_finish("FAIL","ANNUAL_OBSERVATION_FAILED",fields);}catch(const std::exception&){failed=true;}
 runner::atomicWriteFaultStage=nullptr;
 assert(failed&&!finished&&!runner::exists(job.dir(runner::SDROOT)+"/result.kv"));
 // Old records remain readable and lack annual evidence, rather than implying zero.
 auto old=runner::parse("version=1\noutcome=PASS\nframes=9\n");
 assert(old.count("stress_annual_attempts")==0&&old.at("frames")=="9");
}
''')
            native=ROOT/'src/3ds/runner'
            subprocess.run(['c++','-std=c++17','-DCTH3DS_STUB_BUILD','-DCTH3DS_RUNNER_FAULT_TEST',
                '-I'+str(native),str(source),str(native/'core.cpp'),str(native/'rosalina.cpp'),
                '-o',str(work/'probe')],check=True,capture_output=True)
            subprocess.run([str(work/'probe')],cwd=work,check=True,capture_output=True)
