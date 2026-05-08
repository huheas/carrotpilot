#!/usr/bin/env python3
"""
CH347 device diagnostic - check all possible issues
"""
import ctypes
import os

print("="*60)
print("CH347 Device Diagnostic")
print("="*60)

# 1. Check device file
device = "/dev/ch34x_pis1"
print(f"\n1. Checking device file: {device}")
if os.path.exists(device):
    print(f"  ✓ Device exists")
    print(f"  Permissions: {oct(os.stat(device).st_mode)[-3:]}")
    print(f"  Owner: {os.stat(device).st_uid}")
else:
    print(f"  ✗ Device not found")

# 2. Try to open device file directly
print("\n2. Trying to open device file directly...")
try:
    fd = os.open(device, os.O_RDWR)
    print(f"  ✓ Opened successfully (fd: {fd})")

    # Try to read
    print("\n3. Trying to read from device...")
    try:
        data = os.read(fd, 64)
        print(f"  ✓ Read {len(data)} bytes: {data.hex()}")
    except Exception as e:
        print(f"  ✗ Read failed: {e}")

    os.close(fd)
except Exception as e:
    print(f"  ✗ Open failed: {e}")

# 4. Try libch347 with different approaches
print("\n4. Testing libch347.so functions...")
lib = ctypes.cdll.LoadLibrary('/usr/lib/libch347.so')

# Check if there are any init functions
print("\nAvailable CH347 functions:")
functions = []
for name in dir(lib):
    if name.startswith('CH347') and not name.startswith('_'):
        functions.append(name)

for func in sorted(functions)[:20]:
    print(f"  {func}")

# 5. Try CH347OpenDevice with error handling
print("\n5. Testing CH347OpenDevice with detailed error handling...")

# Set proper argtypes BEFORE calling
lib.CH347OpenDevice.argtypes = [ctypes.c_uint32]
lib.CH347OpenDevice.restype = ctypes.c_int32  # Use c_int32 instead of c_int

print("  Calling CH347OpenDevice(0)...")
try:
    # Use ctypes to catch the exact error
    handle = lib.CH347OpenDevice(ctypes.c_uint32(0))
    print(f"  Handle value: {handle}")
    print(f"  Handle type: {type(handle)}")

    if handle > 0:
        print(f"  ✓ Device opened with handle {handle}")
        lib.CH347CloseDevice(handle)
    else:
        print(f"  ✗ Failed to open (returned {handle})")
except Exception as e:
    print(f"  ✗ Exception: {e}")
    import traceback
    traceback.print_exc()

# 6. Check if we need to use /dev/ch34x_pis1 directly
print("\n6. Checking alternative access methods...")
print("  CH347 driver might use different interface...")
print("  Checking /dev/ch34x_pis1 type...")

try:
    import stat
    st = os.stat(device)
    if stat.S_ISCHR(st.st_mode):
        print(f"  ✓ Character device (major: {os.major(st.st_rdev)}, minor: {os.minor(st.st_rdev)})")
except Exception as e:
    print(f"  ✗ Error: {e}")

print("\n" + "="*60)
print("Diagnostic complete")
print("="*60)
print("\nPossible issues:")
print("  1. CH347 device not properly initialized")
print("  2. Library version mismatch")
print("  3. Device permissions (need root?)")
print("  4. LSM6DS3 not properly connected")
print("\nSuggested next steps:")
print("  1. Check if CH347 I2C is enabled in hardware")
print("  2. Verify SDA/SCL connections")
print("  3. Try using vendor's test program")
print("  4. Check CH347 documentation for proper initialization sequence")
