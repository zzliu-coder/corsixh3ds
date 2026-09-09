#include "logging_io_probe.hpp"
#include <cerrno>
#include <algorithm>
#include <cassert>
#include <fstream>
#include <iostream>
#include <iterator>
#include "cth3ds/bounded_log.hpp"

namespace {
int close_cookie(void*) {
  ++logging_io::closes;
  if(logging_io::close_failure){errno=EIO;return -1;}
  return 0;
}
#if defined(__APPLE__)
int write_cookie(void*,const char* text,int count) {
#else
ssize_t write_cookie(void*,const char* text,std::size_t count) {
#endif
  ++logging_io::writes;
  if(logging_io::on_write)logging_io::on_write();
  if(logging_io::writes>logging_io::fail_after){errno=EIO;return -1;}
  const auto size=static_cast<std::size_t>(count);
  const auto accepted=logging_io::short_write&&size?size-1:size;
  logging_io::delivered.append(text,accepted);
  if(logging_io::on_deliver)logging_io::on_deliver(text,accepted);
  if(accepted<size)errno=EIO;
  return static_cast<decltype(count)>(accepted);
}
}
std::FILE* logging_open(const char*,const char*) {
#if defined(__APPLE__)
  return funopen(nullptr,nullptr,write_cookie,nullptr,close_cookie);
#else
  cookie_io_functions_t io{};io.write=write_cookie;io.close=close_cookie;
  return fopencookie(nullptr,"w",io);
#endif
}
#ifndef LOGGING_IO_NO_MAIN
static std::uint64_t cost_clock=0;
static std::uint64_t tick() noexcept {return cost_clock++;}
static void format_line(cth3ds::BoundedLog& log,const char* pattern,...) {
  std::va_list args;va_start(args,pattern);log.vline(pattern,args);va_end(args);
}
static bool open(cth3ds::BoundedLog& log) {
  return log.open("/no-r70-fixture/current","/no-r70-fixture/previous","/no-r70-fixture/oldest");
}
int main(int argc,char** argv) {
  cth3ds::BoundedLog log;
  if(argc==2) {
    std::ifstream source(argv[1],std::ios::binary);
    assert(source.good());
    std::string row,expected;
    std::size_t report=0;
    while(std::getline(source,row)) {
      if(row=="---REPORT---") {
        if(!expected.empty()) {
          assert(log.flush());assert(logging_io::delivered==expected);
          std::cout<<"REPORT "<<++report<<" bytes="<<expected.size()
            <<" explicit_flushes="<<log.flushes()<<" underlying_writes="<<logging_io::writes<<'\n';
          log.close();expected.clear();
        }
        logging_io::reset();assert(open(log));
      } else {
        log.line(row.c_str());expected+=row;expected+='\n';
      }
    }
    assert(log.flush());assert(logging_io::delivered==expected);
    std::cout<<"REPORT "<<++report<<" bytes="<<expected.size()
      <<" explicit_flushes="<<log.flushes()<<" underlying_writes="<<logging_io::writes<<'\n';
    log.close();return 0;
  }
  logging_io::reset();assert(open(log));
  log.line("");log.line(nullptr);log.line("literal %s");
  assert(log.flushes()==0&&logging_io::writes==0);
  assert(log.flush());assert(logging_io::delivered=="\n\nliteral %s\n");
  log.line("fatal-context");log.emergency();
  assert(logging_io::delivered.find("fatal-context\n")!=std::string::npos);
  const auto before=logging_io::writes;log.line("FATAL");
  assert(logging_io::writes==before+1&&logging_io::delivered.find("FATAL\n")!=std::string::npos);
  log.close();assert(logging_io::closes==1&&!log.available());

  for(bool short_result:{false,true}) {
    logging_io::reset();assert(open(log));
    logging_io::short_write=short_result;
    if(!short_result)logging_io::fail_after=0;
    log.line("flush-error");assert(!log.flush());assert(log.failed()&&!log.available());
    const auto accepted=log.bytes(),written=logging_io::writes;
    log.line("ignored");log.write("ignored",7);assert(!log.flush());
    assert(log.bytes()==accepted&&logging_io::writes==written);
    log.close();assert(logging_io::closes==1&&log.failed());
  }
  logging_io::reset();assert(open(log));log.line("close-drains-tail");
  log.close();assert(logging_io::delivered=="close-drains-tail\n");
  logging_io::reset();assert(open(log));logging_io::close_failure=true;
  log.close();assert(log.failed()&&logging_io::closes==1);
  logging_io::reset();assert(open(log));assert(!log.failed()&&log.bytes()==0&&log.flushes()==0);
  log.close();
  logging_io::reset();assert(open(log));log.set_clock(tick);
  format_line(log,"%llu %d %.*s",42ULL,-17,3,"abcdef");
  format_line(log,"float=%.0f",3.0);
  format_line(log,"%.*s",-1,"negative");
  assert(log.costs().format.calls==3 && log.costs().format.total_us==3);
  assert(log.costs().fast==1 && log.costs().fallback==2);
  assert(log.costs().write.calls==3 && log.costs().write.total_us==3);
  logging_io::on_write=[](){cost_clock+=1000;};
  assert(log.flush());assert(log.costs().flush.total_us==1001 && log.costs().flush.max_us==1001);
  assert(logging_io::delivered=="42 -17 abc\nfloat=3\nnegative\n");
  log.emergency();const auto flushes=log.costs().flush.calls;
  format_line(log,"fatal=%u",19U);assert(log.costs().flush.calls==flushes+1);
  logging_io::fail_after=logging_io::writes;format_line(log,"failed=%d",-3);
  assert(log.failed());const auto writes=log.costs().write.calls;
  log.write("ignored",7);assert(log.costs().write.calls==writes);
  log.close();logging_io::reset();assert(open(log));
  assert(log.costs().format.calls==0 && log.costs().write.calls==0 && log.costs().flush.calls==0);
  char reference[256];
  std::snprintf(reference,sizeof(reference),"%08u %zu %.0f %lld %% %s\n",19U,std::size_t{23},7.0,-42LL,"尾部");
  format_line(log,"%08u %zu %.0f %lld %% %s",19U,std::size_t{23},7.0,-42LL,"尾部");
  assert(log.costs().fallback==1 && log.costs().fast==0);
  assert(log.flush() && logging_io::delivered==reference);
  log.set_clock(+[]() noexcept -> std::uint64_t {return --cost_clock;});
  format_line(log,"reverse=%u",1U);assert(!log.costs().valid);
  log.close();logging_io::reset();assert(open(log));log.set_clock(tick);
  auto& costs=const_cast<cth3ds::BoundedLog::Costs&>(log.costs());
  costs.format.calls=std::numeric_limits<std::uint64_t>::max();
  format_line(log,"overflow=%u",1U);
  assert(!costs.valid && costs.format.calls==std::numeric_limits<std::uint64_t>::max());
  log.close();
  std::cout<<"PASS real stdio buffer, short-write, flush/close failure, emergency and reopen\n";
}
#endif
