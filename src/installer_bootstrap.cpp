#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <objbase.h>
#include <array>
#include <string>

#include "setup_data.hpp"

namespace {
constexpr wchar_t title[] = L"Detroit Adaptive Display";
constexpr wchar_t library_name[] = L"DetroitAdaptiveDisplay.SetupData.dll";

struct Resource {
    const unsigned char* data{};
    DWORD size{};
};

Resource read_resource(HMODULE library, WORD id) {
    auto info = FindResourceW(library, MAKEINTRESOURCEW(id), MAKEINTRESOURCEW(10)); // RCDATA
    if (!info) return {};
    auto resource = LoadResource(library, info);
    return {static_cast<const unsigned char*>(LockResource(resource)), SizeofResource(library, info)};
}

bool matches(Resource resource, const std::array<unsigned char, 32>& expected) {
    if (!resource.data || !resource.size) return false;
    BCRYPT_ALG_HANDLE algorithm{};
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0)
        return false;
    std::array<unsigned char, 32> result{};
    BCRYPT_HASH_HANDLE hash{};
    const bool verified = BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) >= 0 &&
                          BCryptHashData(hash, const_cast<unsigned char*>(resource.data), resource.size, 0) >= 0 &&
                          BCryptFinishHash(hash, result.data(), static_cast<ULONG>(result.size()), 0) >= 0 &&
                          result == expected;
    if (hash) BCryptDestroyHash(hash);
    BCryptCloseAlgorithmProvider(algorithm, 0);
    return verified;
}

DWORD write_new_file(const std::wstring& path, Resource resource) {
    HANDLE file = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return GetLastError();
    DWORD written{};
    DWORD error = ERROR_SUCCESS;
    if (!WriteFile(file, resource.data, resource.size, &written, nullptr))
        error = GetLastError();
    else if (written != resource.size)
        error = ERROR_WRITE_FAULT;
    CloseHandle(file);
    if (error != ERROR_SUCCESS) DeleteFileW(path.c_str());
    return error;
}

int report(const std::wstring& path, DWORD error, bool dialog) {
    wchar_t system_message[512]{};
    FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS, nullptr, error, 0,
                   system_message, static_cast<DWORD>(std::size(system_message)), nullptr);
    std::wstring message = path + L"\r\n\r\n" + system_message;
    if (dialog) {
        MessageBoxW(nullptr, message.c_str(), title, MB_OK | MB_ICONERROR);
    } else {
        const int length = WideCharToMultiByte(CP_UTF8, 0, message.data(),
                                              static_cast<int>(message.size()), nullptr, 0, nullptr, nullptr);
        std::string utf8(length, '\0');
        WideCharToMultiByte(CP_UTF8, 0, message.data(), static_cast<int>(message.size()),
                            utf8.data(), length, nullptr, nullptr);
        DWORD written{};
        WriteFile(GetStdHandle(STD_ERROR_HANDLE), utf8.data(), static_cast<DWORD>(utf8.size()), &written, nullptr);
    }
    return 1;
}

int run_installer(Resource runtime, const std::wstring& arguments) {
    wchar_t temp[32768]{};
    DWORD length = GetTempPathW(static_cast<DWORD>(std::size(temp)), temp);
    if (!length || length >= std::size(temp))
        return report(L"%TEMP%", ERROR_PATH_NOT_FOUND, arguments.empty());
    GUID guid{};
    wchar_t identifier[40]{};
    if (FAILED(CoCreateGuid(&guid)) || !StringFromGUID2(guid, identifier, static_cast<int>(std::size(identifier))))
        return report(temp, ERROR_GEN_FAILURE, arguments.empty());
    std::wstring directory = std::wstring(temp, length) + L"DetroitAdaptiveDisplay-" + identifier;
    if (!CreateDirectoryW(directory.c_str(), nullptr))
        return report(directory, GetLastError(), arguments.empty());
    const std::wstring exe = directory + L"\\DetroitAdaptiveDisplay-SetupInternal.exe";
    DWORD error = write_new_file(exe, runtime);
    DWORD code = 1;
    if (error == ERROR_SUCCESS) {
        std::wstring command = L"\"" + exe + L"\" " + arguments;
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        GetStartupInfoW(&startup);
        startup.dwFlags &= STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
        PROCESS_INFORMATION child{};
        const BOOL inherit_handles = (startup.dwFlags & STARTF_USESTDHANDLES) != 0;
        if (CreateProcessW(exe.c_str(), command.data(), nullptr, nullptr, inherit_handles, 0,
                           nullptr, nullptr, &startup, &child)) {
            CloseHandle(child.hThread);
            if (WaitForSingleObject(child.hProcess, INFINITE) != WAIT_OBJECT_0 ||
                !GetExitCodeProcess(child.hProcess, &code))
                error = GetLastError();
            CloseHandle(child.hProcess);
        } else {
            error = GetLastError();
        }
        DeleteFileW(exe.c_str());
    }
    RemoveDirectoryW(directory.c_str());
    return error == ERROR_SUCCESS ? static_cast<int>(code) : report(exe, error, arguments.empty());
}
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR command_line, int) {
    const std::wstring arguments = command_line;
    wchar_t module[32768]{};
    const DWORD length = GetModuleFileNameW(nullptr, module, static_cast<DWORD>(std::size(module)));
    if (!length || length >= std::size(module))
        return report(title, ERROR_PATH_NOT_FOUND, arguments.empty());
    std::wstring directory(module, length);
    directory.resize(directory.find_last_of(L"\\/") + 1);
    const std::wstring library_path = directory + library_name;
    HMODULE library = LoadLibraryExW(library_path.c_str(), nullptr,
                                     LOAD_LIBRARY_AS_DATAFILE_EXCLUSIVE | LOAD_LIBRARY_AS_IMAGE_RESOURCE);
    if (!library) return report(library_path, GetLastError(), arguments.empty());
    const bool export_source = arguments == L"--extract-source";
    const auto resource = read_resource(library, export_source ? 102 : 101);
    int result = 1;
    if (!matches(resource, export_source ? setup_data::source : setup_data::runtime)) {
        result = report(library_path, ERROR_CRC, arguments.empty());
    } else if (export_source) {
        const auto path = directory + setup_data::source_filename;
        const auto error = write_new_file(path, resource);
        result = error == ERROR_SUCCESS ? 0 : report(path, error, false);
    } else {
        result = run_installer(resource, arguments);
    }
    FreeLibrary(library);
    return result;
}
