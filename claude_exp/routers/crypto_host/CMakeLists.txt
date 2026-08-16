cmake_minimum_required(VERSION 3.20)
project(crypto_host CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

find_package(OpenSSL REQUIRED)
find_package(Threads REQUIRED)

include(FetchContent)
FetchContent_Declare(httplib GIT_REPOSITORY https://github.com/yhirose/cpp-httplib.git GIT_TAG v0.15.3)
FetchContent_Declare(json    GIT_REPOSITORY https://github.com/nlohmann/json.git       GIT_TAG v3.11.3)
FetchContent_Declare(catch2  GIT_REPOSITORY https://github.com/catchorg/Catch2.git      GIT_TAG v3.5.4)
FetchContent_MakeAvailable(httplib json catch2)

# Promoted from router_cpp/src/simulators/crypto_host/ - real OpenSSL-backed crypto validation, now
# shared across all three router implementations (router_py/router_java/router_cpp) instead of duplicated per
# language. Only the shared/ files crypto_host actually needs come along; router_config.cpp is
# reused as-is (it tolerates a config file with no upstream/downstream section), which is why
# ebcdic/framing still have to be linked in even though crypto_host itself never calls them --
# router_config.cpp's parse_downstream()/parse_upstream() reference them unconditionally.
add_library(crypto_host_shared STATIC
    src/shared/hex.cpp
    src/shared/base64.cpp
    src/shared/ebcdic.cpp
    src/shared/framing.cpp
    src/shared/iso_codec.cpp
    src/shared/stats.cpp
    src/shared/log.cpp
    src/shared/crypto_utils.cpp
    src/shared/command_server.cpp
    src/shared/pans_defined.cpp
    src/router/router_config.cpp
)
target_include_directories(crypto_host_shared PUBLIC src)
target_link_libraries(crypto_host_shared PUBLIC httplib nlohmann_json::nlohmann_json
                                                 OpenSSL::SSL OpenSSL::Crypto Threads::Threads)
# PUBLIC: cpp-httplib (header-only) gates its SSLClient/SSLServer classes behind this macro,
# checked at whatever TU first includes httplib.h - every target linking crypto_host_shared needs
# it too, not just this library's own .cpp files (see router_cpp/CMakeLists.txt, same pattern).
target_compile_definitions(crypto_host_shared PUBLIC CPPHTTPLIB_OPENSSL_SUPPORT)

add_executable(crypto_host src/simulators/crypto_host/crypto_host_main.cpp)
target_include_directories(crypto_host PRIVATE src)
target_link_libraries(crypto_host PRIVATE crypto_host_shared)

enable_testing()
add_executable(crypto_host_tests test/crypto_utils_test.cpp)
target_link_libraries(crypto_host_tests PRIVATE crypto_host_shared Catch2::Catch2WithMain)
include(CTest)
include(Catch)
catch_discover_tests(crypto_host_tests)
