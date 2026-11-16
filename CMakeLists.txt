# Generated Cmake Pico project file

cmake_minimum_required(VERSION 3.13)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Initialise pico_sdk from installed location
# (note this can come from environment, CMake cache etc)

# == DO NOT EDIT THE FOLLOWING LINES for the Raspberry Pi Pico VS Code Extension to work ==
if(WIN32)
    set(USERHOME $ENV{USERPROFILE})
else()
    set(USERHOME $ENV{HOME})
endif()
set(sdkVersion 2.2.0)
set(toolchainVersion 14_2_Rel1)
set(picotoolVersion 2.2.0-a4)
set(picoVscode ${USERHOME}/.pico-sdk/cmake/pico-vscode.cmake)
if (EXISTS ${picoVscode})
    include(${picoVscode})
endif()
# ====================================================================================
set(PICO_BOARD pico2 CACHE STRING "Board type")

# Pull in Raspberry Pi Pico SDK (must be before project)
include(pico_sdk_import.cmake)

project(FS27-DAQ C CXX ASM)

# Initialise the Raspberry Pi Pico SDK
pico_sdk_init()

# Radio/LoRa TX configuration

# Add subdirectories for the libraries
add_subdirectory(./src/gpio)
add_subdirectory(./src/spi)
add_subdirectory(./src/lr1121)
add_subdirectory(./src/mcp2515)

# Add include directories
include_directories(./src/gpio)
include_directories(./src/spi)
include_directories(./src/lr1121)
include_directories(./src/mcp2515)

# Include the LR1121 radio config and TX files
include_directories(${CMAKE_CURRENT_SOURCE_DIR})

# Add executable. Default name is the project name, version 0.1

add_executable(FS27-DAQ
    FS26-DAQ_fs27.c
    gps_fs27.c
    lr1121_config.c
    lr1121_tx.c
    can_handler_fs27.c
    ft550_decoder.c
    daq_settings_fs27.c
    daq_flash_fs27.c daq_inputs_fs27.c
)

pico_set_program_name(FS27-DAQ "FS27-DAQ")
pico_set_program_version(FS27-DAQ "2.0")

# Modify the below lines to enable/disable output over UART/USB
pico_enable_stdio_uart(FS27-DAQ 0)
pico_enable_stdio_usb(FS27-DAQ 1)

# 2. Add pico_multicore here to fix the 'multicore_launch_core1' error
target_link_libraries(FS27-DAQ
        pico_stdlib
        pico_multicore
        pico_flash
        hardware_flash
        hardware_adc
        hardware_i2c
        gpio
        spi
        lr1121
        mcp2515
)

# 4 KB is the most each core's stack can have on the RP2350 (the default is 2 KB)
target_compile_definitions(FS27-DAQ PRIVATE PICO_STACK_SIZE=0x1000 PICO_CORE1_STACK_SIZE=0x1000)

# Add the standard include files to the build
target_include_directories(FS27-DAQ PRIVATE
        ${CMAKE_CURRENT_LIST_DIR}
)

pico_add_extra_outputs(FS27-DAQ)

