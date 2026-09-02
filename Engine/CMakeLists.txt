cmake_minimum_required(VERSION 3.24)

project(a2f_blender_exporter LANGUAGES CXX)

set(A2F_SDK_ROOT "${CMAKE_CURRENT_LIST_DIR}/../Audio2Face-3D-SDK" CACHE PATH "Audio2Face 3D SDK root")
set(A2F_BUILD_DIR "${A2F_SDK_ROOT}/build" CACHE PATH "Audio2Face SDK build directory")

add_executable(a2f_blender_exporter src/main.cpp)
target_compile_features(a2f_blender_exporter PRIVATE cxx_std_17)
target_compile_definitions(a2f_blender_exporter PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
target_include_directories(a2f_blender_exporter PRIVATE "${A2F_BUILD_DIR}/audio2x-sdk/include")
target_link_libraries(a2f_blender_exporter PRIVATE
  "${A2F_BUILD_DIR}/audio2x-sdk/lib/audio2x.lib"
  mfplat mfreadwrite mfuuid ole32
)

if(MSVC)
  target_compile_options(a2f_blender_exporter PRIVATE /W4 /permissive- /EHsc /utf-8)
endif()
