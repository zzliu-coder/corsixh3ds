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
  std::cout<<"PASS real stdio buffer, short-write, flush/close failure, emergency and reopen\n";
}
#endif
