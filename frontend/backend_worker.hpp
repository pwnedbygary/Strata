#pragma once
#include "memory_policy.hpp"
#include <sys/file.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <unistd.h>
#include <csignal>
#include <chrono>
#include <thread>
#include <fstream>
#include <sstream>
namespace native_backend {
inline std::string birth(pid_t pid) {
    std::ifstream f("/proc/"+std::to_string(pid)+"/stat");std::string line;std::getline(f,line);
    auto pos=line.rfind(')');if(pos==std::string::npos)return "";
    std::istringstream in(line.substr(pos+2));std::string token;
    for(int field=3;field<=22;++field)if(!(in>>token))return "";return token;
}
inline int worker(int argc,char **argv) {
    if(argc<7)return 2;
    const auto ram_floor=std::stoull(argv[3])*native_memory::MiB;
    const auto vram_floor=std::stoll(argv[4])*(int64_t)native_memory::MiB;
    const pid_t owner=std::stoi(argv[2]);const auto owner_birth=birth(owner);
    if(owner_birth.empty()||!native_memory::snapshot().cgroup_limit)return 2;
    const char *runtime=getenv("XDG_RUNTIME_DIR");const auto path=(runtime?std::string(runtime):"/tmp")+"/strata-native-model-"+std::to_string(getuid())+".lock";
    int lock=open(path.c_str(),O_CREAT|O_RDWR|O_CLOEXEC|O_NOFOLLOW,0600);
    if(lock<0||flock(lock,LOCK_EX|LOCK_NB))return 2;
    auto parent=getpid();auto child=fork();if(child<0)return 2;
    if(child==0) {
        prctl(PR_SET_PDEATHSIG,SIGKILL);if(getppid()!=parent)_exit(2);
        for(char **e=environ;*e;) {std::string key=*e;key=key.substr(0,key.find('='));
            if(key.rfind("LLAMA_ARG_",0)==0){unsetenv(key.c_str());e=environ;}else ++e;}
        if(const char *key=getenv("STRATA_API_KEY"))setenv("LLAMA_API_KEY",key,1);else unsetenv("LLAMA_API_KEY");
        execvp(argv[5],argv+5);_exit(127);
    }
    prctl(PR_SET_NAME,"strata-llama",0,0,0);
    while(true) {
        int st=0;auto done=waitpid(child,&st,WNOHANG);
        if(done==child)return WIFEXITED(st)?WEXITSTATUS(st):128+WTERMSIG(st);
        if(done<0&&errno!=EINTR)return 2;
        auto m=native_memory::snapshot();
        const bool low=m.available<ram_floor||(m.vram_free>=0&&m.vram_free<vram_floor)||
            (m.cgroup_limit>256*native_memory::MiB&&m.cgroup_used>m.cgroup_limit-256*native_memory::MiB);
        if(birth(owner)!=owner_birth||low) {
            kill(child,SIGKILL);waitpid(child,&st,0);
            if(low)std::fprintf(stderr,"llama.cpp worker stopped before memory headroom was exhausted\n");
            return low?75:2;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }
}
}
