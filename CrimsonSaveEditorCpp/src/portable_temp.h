/**
 * portable_temp.h — cross-platform temporary file path.
 *
 * Replaces the Win32-only GetTempPathA/MAX_PATH pattern and the
 * getenv("TEMP") + backslash join that produced a bogus path on Linux.
 * Works on Windows, Linux and macOS with no platform ifdefs.
 */
#pragma once

#include <atomic>
#include <filesystem>
#include <string>

namespace PortableTemp {

inline std::filesystem::path temp_file(const char* prefix) {
    static std::atomic<unsigned> counter{0};
    return std::filesystem::temp_directory_path() /
           (std::string(prefix) + std::to_string(counter.fetch_add(1)) + ".tmp");
}

inline void remove_file(const std::filesystem::path& path) {
    std::error_code ec;
    std::filesystem::remove(path, ec);
}

} // namespace PortableTemp
