// CorsixTH adapter; protocol implementation reused from old3ds-runner cab2721.
#include "adapter.hpp"
#include "rosalina.hpp"
#include <cstdio>
#include <stdexcept>
#include <sys/stat.h>
#include <dirent.h>
#include <algorithm>
#include <chrono>
namespace cth3ds {
namespace {
runner::Job job;
runner::Fields config;
bool active=false, finished=false;
bool interactive=false;
std::chrono::steady_clock::time_point session_started;
unsigned long long frames=0;
unsigned checkpoint_sequence=0;
void require(bool ok,const char* reason){if(!ok)throw std::runtime_error(reason);}
void luaFiles(const std::string& base,const std::string& relative,std::vector<std::string>& rows){
  DIR* directory=opendir((base+relative).c_str());require(directory!=nullptr,"lua_directory_missing");
  std::vector<std::string> names;
  while(auto* entry=readdir(directory))if(entry->d_name[0]!='.')names.emplace_back(entry->d_name);
  closedir(directory);
  for(const auto& name:names){
    const auto path=relative+name;struct stat info{};
    require(stat((base+path).c_str(),&info)==0,"lua_stat_failed");
    if(S_ISDIR(info.st_mode))luaFiles(base,path+"/",rows);
    else if(path.size()>4&&path.substr(path.size()-4)==".lua"){
      require(rows.size()<4096,"lua_file_limit");
      rows.push_back(path+"|"+runner::hashFile(base+path)+"\n");
    }
  }
}
void copy(const std::string& from,const std::string& to){
  FILE* in=std::fopen(from.c_str(),"rb");require(in!=nullptr,"copy_input_open");
  FILE* out=std::fopen(to.c_str(),"wb");
  if(!out){std::fclose(in);throw std::runtime_error("copy_output_open");}
  char buffer[4096];size_t n;bool ok=true;
  while((n=std::fread(buffer,1,sizeof(buffer),in)))if(std::fwrite(buffer,1,n,out)!=n){ok=false;break;}
  ok=ok&&!std::ferror(in);std::fclose(in);if(std::fclose(out))ok=false;
  require(ok&&runner::hashFile(from)==runner::hashFile(to),"copy_readback_failed");
}
}
bool runner_active() noexcept{return active;}
bool runner_interactive() noexcept{return active&&interactive;}
const runner::Fields& runner_config(){return config;}
std::string runner_directory(){return active?job.dir(runner::SDROOT):"";}
void runner_present(bool success) noexcept {if(active&&success)++frames;}
unsigned long long runner_frames() noexcept{return frames;}
void runner_checkpoint(const runner::Fields& metrics){
  require(active&&!finished,"checkpoint_requires_active_run");
  require(checkpoint_sequence<48,"checkpoint_count_limit");
  runner::Fields fields={{"version","1"},{"run_id",job.id},{"artifact_sha256",job.sha},
    {"config_sha256",job.configSha},{"input_sha256",job.inputSha},{"manifest_sha256",job.manifestSha},
    {"checkpoint_sequence",std::to_string(checkpoint_sequence+1)},{"snapshot_complete","1"}};
  for(const auto& metric:metrics){
    require(fields.count(metric.first)==0,"reserved_checkpoint_field");
    fields.emplace(metric);
  }
  const auto bytes=runner::encode(fields);
  require(bytes.size()<=16384,"checkpoint_exceeds_protocol_limit");
  (void)runner::parse(bytes); // Validate key/value bytes before creating a file.
  char name[40];std::snprintf(name,sizeof(name),"/artifacts/progress-%04u.kv",checkpoint_sequence+1);
  runner::atomicWriteNew(job.dir(runner::SDROOT)+name,bytes);
  ++checkpoint_sequence;
}
void runner_finish(const std::string& outcome,const std::string& reason,const runner::Fields& metrics){
  if(!active||finished)return;
  require(outcome=="PASS"||outcome=="FAIL"||outcome=="NOT_PROVEN","invalid_outcome");
  require(!runner_interactive()||outcome!="PASS","interactive_requires_human_confirmation");
  std::string safe_reason=reason.substr(0,240);
  std::replace(safe_reason.begin(),safe_reason.end(),'\n',' ');
  std::replace(safe_reason.begin(),safe_reason.end(),'\r',' ');
  runner::Fields result={{"version","1"},{"run_id",job.id},{"artifact_sha256",job.sha},
    {"config_sha256",job.configSha},{"input_sha256",job.inputSha},{"manifest_sha256",job.manifestSha},
    {"phase","complete"},{"outcome",outcome},{"reason",safe_reason},
    {"workload",runner_interactive()?"corsixth-r74-interactive-v1":"corsixth-r63-fixed-wall-v1"},{"simulation_ticks","0"},{"frames","0"},{"elapsed_us","0"},
    {"assets_full_reverified","0"},{"assets_receipt_sha256",config["assets_receipt_sha256"]}};
  for(const auto& field:metrics){
    require(field.first!="version"&&field.first!="run_id"&&field.first!="artifact_sha256"&&
      field.first!="config_sha256"&&field.first!="input_sha256"&&field.first!="manifest_sha256"&&
      field.first!="phase"&&field.first!="outcome"&&field.first!="reason"&&field.first!="workload"&&
      field.first!="assets_full_reverified"&&field.first!="assets_receipt_sha256","reserved_result_metric");
    require(field.first.size()<=64&&field.first.find_first_not_of("abcdefghijklmnopqrstuvwxyz_0123456789")==std::string::npos&&
      field.second.size()<=1024&&field.second.find_first_of("\r\n") == std::string::npos,"invalid_result_metric");
    result[field.first]=field.second;
  }
  const auto bytes=runner::encode(result);
  require(bytes.size()<=16384,"result_exceeds_protocol_limit");
  runner::atomicWrite(job.dir(runner::SDROOT)+"/result.kv",bytes);finished=true;
}
void runner_process_exit() noexcept {
  // main calls this only after its Lua restart loop has ended. Runtime shutdown
  // also occurs inside that loop and cannot complete an interactive session.
  if(!runner_interactive()||finished)return;
  try {
    const auto elapsed=std::chrono::duration_cast<std::chrono::microseconds>(
      std::chrono::steady_clock::now()-session_started).count();
    runner_finish("NOT_PROVEN","needs_human_confirmation",{
      {"frames",std::to_string(frames)},{"elapsed_us",std::to_string(elapsed)},
      {"simulation_ticks_available","0"},{"human_confirmation","required"}});
  }catch(const std::exception& e){std::fprintf(stderr,"runner exit: %s\n",e.what());}
}
int runner_start(int argc,char** argv) noexcept {
  // Ordinary hbmenu launches carry no run tuple. Malformed automation never
  // falls through to the player's configuration or one-shot marker.
  try{
    if(!argv||!argv[0]||std::string(argv[0]).rfind(std::string(runner::SDROOT)+"/runs/",0)!=0)return 0;
    require(argc==3&&argv[1]&&argv[2]&&runner::validId(argv[1])&&runner::validHash(argv[2]),"invalid_runner_arguments");
    runner::nextLoad(runner::SELF,{});
    job=runner::loadJob(runner::SDROOT,runner::encode({{"run_id",argv[1]},{"manifest_sha256",argv[2]}}),true);
    require(argv[0]==job.target(runner::SDROOT),"executed_path_mismatch");
    const auto dir=job.dir(runner::SDROOT);
    require(!runner::exists(dir+"/started.kv")&&!runner::exists(dir+"/result.kv"),"run_id_already_started");
    active=true;
    config=runner::parse(runner::read(dir+"/config.bin",1024*1024));
    if(config.count("interactive")){
      require(config.at("interactive")=="r74-v1","unknown_interactive_version");
      require(config["profile"]=="zh-on"&&config["stress_ms"]=="0"&&
        !config.count("capacity")&&!config.count("recovery_sha256")&&
        !config.count("expanded_sha256")&&!config.count("continuity_sha256"),
        "invalid_interactive_configuration");
      interactive=true;
      session_started=std::chrono::steady_clock::now();
    }
    require(config["adapter"]=="corsixth-r63-v1","unknown_adapter");
    require(config["profile"]=="zh-on"||config["profile"]=="expanded-zh-on"||config["profile"]=="matrix","unknown_profile");
    require(runner::validHash(config["assets_receipt_sha256"]),"missing_asset_receipt_identity");
    require(runner::validHash(config["lua_tree_sha256"]),"missing_lua_tree_identity");
    std::vector<std::string> rows;luaFiles("sdmc:/3ds/corsixth/Lua/","",rows);
    std::sort(rows.begin(),rows.end());std::string tree;
    for(const auto& row:rows)tree+=row;
    require(!rows.empty()&&runner::sha256(tree)==config["lua_tree_sha256"],"installed_lua_tree_mismatch");
    require(runner::validHash(config["player_config_sha256"])&&
      runner::hashFile("sdmc:/3ds/corsixth/config.txt")==config["player_config_sha256"],"player_config_mismatch");
    const int duration=std::stoi(config.at("stress_ms"));
    require(std::to_string(duration)==config["stress_ms"]&&duration>=0&&duration<=22*60000,"invalid_stress_duration");
    if(config.count("capacity")){
      require((config.at("capacity")=="r73-v1"||config.at("capacity")=="r74-v1")&&config["profile"]=="expanded-zh-on"&&duration>0&&duration<=180000&&
        !config.count("recovery_sha256"),"invalid_capacity_configuration");
      require(config["continuity_sha256"]=="17b74375444d153599873bf25255b0d6a817343382eed1ebab6d3d89dce3a808",
        "invalid_continuity_identity");
      require(config["expanded_sha256"]=="f8a8039644a81a22b44fd1dfed6201c70782ae6bf4873bdb50b3ba7b2c63a0e7",
        "invalid_capacity_expanded_identity");
      unsigned index=0;
      for(const auto& identity:{
        "c792571dfaeee2b44fca9f3d5100e3baf878580657d471c10f24ba23ff032253|sdmc:/3ds/corsixth/game/LEVELS/LEVEL.L1",
        "e0c70a7c5d7034b63063901487b94c7b2924b6cf972c7a773f70175e89b407d8|sdmc:/3ds/corsixth/game/LEVELS/LEVEL.L12",
        "03ef32ce27867196ac5991025de59d658254e3287cf4c9dd73a7c3824bddfd2b|sdmc:/3ds/corsixth/game/LEVELS/FULL00.SAM",
        "38beafde190313e57034bc8295a07660921c4d7c67568850a57a3f6c4cc27f0b|sdmc:/3ds/corsixth/game/LEVELS/FULL12.SAM"}){
        require(config["verify_"+std::to_string(++index)]==identity,"invalid_capacity_asset_identity");
      }
    }else require(!config.count("continuity_sha256"),"continuity_requires_capacity");
    for(const auto& key:{"warmup_ms","sample_ms"}){
      const int ms=std::stoi(config.at(key));
      require(std::to_string(ms)==config[key]&&ms>=1000&&ms<=60000,"invalid_sample_duration");
    }
    // Explicit file identities bind installed Lua and integration receipts.
    unsigned verified=0;
    for(const auto& f:config)if(f.first.rfind("verify_",0)==0){
      require(f.second.size()>65&&f.second[64]=='|',"invalid_dependency_identity");
      const auto path=f.second.substr(65), hash=f.second.substr(0,64);
      require(path.rfind("sdmc:/3ds/corsixth/",0)==0&&path.find("..") == std::string::npos,"invalid_dependency_path");
      require(runner::validHash(hash)&&runner::hashFile(path)==hash,"dependency_hash_mismatch");++verified;
    }
    require(verified>0,"missing_dependency_manifest");
    require(mkdir((dir+"/save").c_str(),0777)==0,"private_save_directory_exists");
    mkdir((dir+"/artifacts").c_str(),0777);
    copy("sdmc:/3ds/corsixth/config.txt",dir+"/save/config.txt");
    copy(dir+"/input.bin",dir+"/input.sav");
    if(runner_interactive())copy(dir+"/input.bin",dir+"/save/Acceptance.sav");
    for(const auto& name:{"expanded","r62-recovery","continuity"}){
      auto it=config.find(std::string(name)=="expanded"?"expanded_sha256":
        std::string(name)=="continuity"?"continuity_sha256":"recovery_sha256");
      if(it!=config.end()){
        const std::string source=std::string("sdmc:/3ds/corsixth/Benchmark/")+name+".sav";
        require(runner::validHash(it->second)&&runner::hashFile(source)==it->second,"baseline_hash_mismatch");
        copy(source,dir+"/"+name+".sav");
      }
    }
    require(config["profile"]=="zh-on"||runner::exists(dir+"/expanded.sav"),"profile_requires_expanded_baseline");
    runner::atomicWrite(dir+"/started.kv",runner::encode({{"run_id",job.id},{"phase","running"},{"artifact_sha256",job.sha}}));
    return 1;
  }catch(const std::exception& e){
    std::fprintf(stderr,"runner: %s\n",e.what());
    try{runner_finish("NOT_PROVEN",e.what());}catch(...){}
    return -1;
  }
}
}
