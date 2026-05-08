#!/usr/bin/env python3
"""
Simple CH347 test - step by step
"""
import ctypes
import time

print("="*60)
print("CH347 Simple Test")
print("="*60)

# Load library
lib = ctypes.cdll.LoadLibrary('/usr/lib/libch347.so')
print("✓ Library loaded")

# Step 1: Get device info
print("\n1. Getting device info...")
lib.CH347GetDeviceInfor.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
lib.CH347GetDeviceInfor.restype = ctypes.c_int

buffer = ctypes.create_string_buffer(256)
result = lib.CH347GetDeviceInfor(0, buffer, len(buffer))
if result == 1:
    print(f"✓ Device info: {buffer.value.decode()}")
else:
    print(f"✗ Failed to get device info: {result}")

# Step 2: Open device
print("\n2. Opening device...")
lib.CH347OpenDevice.restype = ctypes.c_int
lib.CH347OpenDevice.argtypes = [ctypes.c_uint32]

handle = lib.CH347OpenDevice(0)
print(f"  Handle: {handle}")

if handle < 0:
    print(f"✗ Failed to open device")
    exit(1)

print(f"✓ Device opened successfully")

# Step 3: Configure I2C
print("\n3. Configuring I2C...")
lib.CH347I2C_Set.restype = ctypes.c_int
lib.CH347I2C_Set.argtypes = [ctypes.c_uint32, ctypes.c_uint32]

# Speed: 0=Low(20kHz), 1=Standard(100kHz), 2=Fast(400kHz)
result = lib.CH347I2C_Set(handle, 1)  # Standard speed
if result == 1:
    print("✓ I2C configured (100kHz)")
else:
    print(f"✗ I2C config failed: {result}")

# Step 4: Read chip ID from LSM6DS3
print("\n4. Reading LSM6DS3 chip ID (address 0x6A, reg 0x0F)...")

# Try CH347StreamI2C
lib.CH347StreamI2C.restype = ctypes.c_int
lib.CH347StreamI2C.argtypes = [
    ctypes.c_uint32,  # handle
    ctypes.c_uint32,  # device address
    ctypes.c_uint32,  # write length
    ctypes.POINTER(ctypes.c_ubyte),  # write buffer
    ctypes.c_uint32,  # read length
    ctypes.POINTER(ctypes.c_ubyte),  # read buffer
]

# Prepare buffers
write_buf = (ctypes.c_ubyte * 1)(0x0F)  # Register address
read_buf = (ctypes.c_ubyte * 1)(0)

result = lib.CH347StreamI2C(
    handle,
    0x6A,  # LSM6DS3 I2C address
    1,     # Write 1 byte (register)
    write_buf,
    1,     # Read 1 byte (chip ID)
    read_buf
)

if result == 1:
    chip_id = read_buf[0]
    print(f"✓ Chip ID: 0x{chip_id:02X}")
    if chip_id in [0x69, 0x6A]:
        print("✓ LSM6DS3 detected!")
    else:
        print(f"⚠ Unknown chip: 0x{chip_id:02X}")
else:
    print(f"✗ I2C read failed: {result}")

    # Try alternative: maybe device address needs to be shifted
    print("\nTrying with shifted address (0xD4)...")
    result = lib.CH347StreamI2C(
        handle,
        0xD4,  # 0x6A << 1
        1,
        write_buf,
        1,
        read_buf
    )

    if result == 1:
        chip_id = read_buf[0]
        print(f"✓ Chip ID: 0x{chip_id:02X}")
    else:
        print(f"✗ Still failed: {result}")

# Step 5: Close device
print("\n5. Closing device...")
lib.CH347CloseDevice(handle)
print("✓ Device closed")

print("\n" + "="*60)
print("Test complete")
print("="*60)
