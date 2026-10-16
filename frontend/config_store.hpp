#pragma once
#include "profiles.hpp"
#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
namespace native_config {
inline std::filesystem::path temporary(const common_json &cfg, const std::filesystem::path &directory) {
    std::string pattern=(directory/".strata-native-XXXXXX").string();
    std::vector<char> name(pattern.begin(),pattern.end());name.push_back(0);
    int fd=::mkstemp(name.data());
    if(fd<0)throw std::runtime_error("Cannot create native configuration file");
    try {
        ::fcntl(fd,F_SETFD,FD_CLOEXEC);
        auto text=cfg.dump_safe()+"\n";size_t done=0;
        while(done<text.size()) {
            auto n=::write(fd,text.data()+done,text.size()-done);
            if(n<0&&errno==EINTR)continue;
            if(n<=0)throw std::runtime_error("Cannot write native configuration file");
            done+=static_cast<size_t>(n);
        }
        if(::fsync(fd))throw std::runtime_error("Cannot sync native configuration file");
        ::close(fd);return name.data();
    } catch(...) {::close(fd);::unlink(name.data());throw;}
}
inline void save(const common_json &cfg, const std::filesystem::path &target) {
    auto next=temporary(cfg,target.parent_path());
    try {
        std::filesystem::rename(next,target);
        int dir = ::open(target.parent_path().c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
        if (dir >= 0) { ::fsync(dir); ::close(dir); }
    }
    catch(...) {std::filesystem::remove(next);throw;}
}
}
