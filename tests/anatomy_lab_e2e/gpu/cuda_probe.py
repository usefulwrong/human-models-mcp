"""Use the NVIDIA Driver API in the container and verify a device-written value."""
from ctypes import CDLL, byref, c_int, c_size_t, c_uint, c_uint64, c_void_p, create_string_buffer


driver = CDLL("libcuda.so.1")


def check(code):
    assert code == 0, f"CUDA driver error {code}"


device = c_int()
version = c_int()
context = c_void_p()
name = create_string_buffer(128)
ptr = c_uint64()
check(driver.cuInit(0))
check(driver.cuDriverGetVersion(byref(version)))
check(driver.cuDeviceGet(byref(device), 0))
check(driver.cuDeviceGetName(name, len(name), device))
check(driver.cuDevicePrimaryCtxRetain(byref(context), device))
check(driver.cuCtxSetCurrent(context))
check(driver.cuMemAlloc_v2(byref(ptr), c_size_t(16)))
try:
    check(driver.cuMemsetD32_v2(ptr, c_uint(41), c_size_t(4)))
    check(driver.cuCtxSynchronize())
    values = (c_uint * 4)()
    check(driver.cuMemcpyDtoH_v2(values, ptr, c_size_t(16)))
    assert list(values) == [41] * 4
    print(f"device={name.value.decode()}, driver_api={version.value}, device_write_readback={list(values)}")
finally:
    check(driver.cuMemFree_v2(ptr))
    check(driver.cuDevicePrimaryCtxRelease_v2(device))
