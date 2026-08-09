cmake_minimum_required(VERSION 3.20)
project(router_cpp CXX)

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

add_library(xv6_shared STATIC
    src/shared/hex.cpp
    src/shared/base64.cpp
    src/shared/ebcdic.cpp
    src/shared/framing.cpp
    src/shared/ims_connect.cpp
    src/shared/iso_codec.cpp
    src/shared/stats.cpp
    src/shared/log.cpp
    src/shared/command_server.cpp
    src/shared/pans_defined.cpp
)
target_include_directories(xv6_shared PUBLIC src)
target_link_libraries(xv6_shared PUBLIC httplib nlohmann_json::nlohmann_json
                                          OpenSSL::SSL OpenSSL::Crypto Threads::Threads)

add_library(xv6_router STATIC
    src/router/router_config.cpp
    src/router/upstream.cpp
    src/router/downstream_connection.cpp
    src/router/crypto_client.cpp
    src/router/dispatcher.cpp
    src/router/router_session.cpp
    src/router/trace_recorder.cpp
)
target_include_directories(xv6_router PUBLIC src)
target_link_libraries(xv6_router PUBLIC xv6_shared)

add_executable(router_main src/router/router_main.cpp)
target_include_directories(router_main PRIVATE src)
target_link_libraries(router_main PRIVATE xv6_router xv6_shared)

add_executable(crypto_host src/simulators/crypto_host/crypto_host_main.cpp)
target_include_directories(crypto_host PRIVATE src)
target_link_libraries(crypto_host PRIVATE xv6_router xv6_shared)

add_executable(downstream_host src/simulators/downstream_host/downstream_host_main.cpp)
target_include_directories(downstream_host PRIVATE src)
target_link_libraries(downstream_host PRIVATE xv6_router xv6_shared)

enable_testing()
file(GLOB TEST_SOURCES CONFIGURE_DEPENDS test/*.cpp)
add_executable(xv6_tests ${TEST_SOURCES})
target_link_libraries(xv6_tests PRIVATE xv6_router xv6_shared Catch2::Catch2WithMain)
include(CTest)
include(Catch)
catch_discover_tests(xv6_tests)
