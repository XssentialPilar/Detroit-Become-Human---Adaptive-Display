#pragma once
#include <windows.h>
#include <bcrypt.h>
#include <algorithm>
#include <array>
#include <cstring>
#include <vector>
#include "engine_profile.hpp"

namespace adaptive {
inline bool matches_engine_image(const wchar_t* path) {
    using namespace engine_profile;
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                              FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER length{};
    BCRYPT_ALG_HANDLE algorithm{};
    BCRYPT_HASH_HANDLE hash{};
    bool ok = GetFileSizeEx(file, &length) && length.QuadPart >= size &&
              BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0 &&
              BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) >= 0;
    std::vector<unsigned char> buffer(1024 * 1024);
    unsigned remaining = size;
    while (ok && remaining) {
        DWORD count = 0;
        const auto wanted = (std::min)(remaining, static_cast<unsigned>(buffer.size()));
        ok = ReadFile(file, buffer.data(), wanted, &count, nullptr) && count == wanted;
        if (!ok) break;
        if (remaining == size) {
            static_assert(certificate + 8 <= 4096 && timestamp + 4 <= 4096 && checksum + 4 <= 4096);
            DWORD table[2]{};
            std::memcpy(table, buffer.data() + certificate, sizeof(table));
            const auto trailing = length.QuadPart - size;
            if (table[0] != (trailing ? size : 0) || table[1] != trailing) {
                ok = false;
                break;
            }
            std::memset(buffer.data() + timestamp, 0, 4);
            std::memset(buffer.data() + checksum, 0, 4);
            std::memset(buffer.data() + certificate, 0, 8);
        }
        ok = BCryptHashData(hash, buffer.data(), count, 0) >= 0;
        remaining -= count;
    }
    std::array<unsigned char, 32> digest{};
    ok = ok && BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) >= 0;
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    CloseHandle(file);
    constexpr char hex[] = "0123456789abcdef";
    for (size_t i = 0; ok && i < digest.size(); ++i)
        ok = hex[digest[i] >> 4] == sha256[2*i] && hex[digest[i] & 15] == sha256[2*i+1];
    return ok;
}
}
