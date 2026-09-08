cmake_minimum_required(VERSION 3.22)

set(TARGET TextTranslatorCpp)
project(${TARGET})

add_library(${TARGET} SHARED
    src/dllmain.cpp
)

target_include_directories(${TARGET} PRIVATE include)
target_link_libraries(${TARGET} PUBLIC UE4SS)
