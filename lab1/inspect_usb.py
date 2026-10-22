"""Read USB descriptor and negotiated-speed flags through Windows hub queries.

Only read-only DeviceIoControl requests are issued. No device is ejected, reset,
or written. Device serial numbers and full device paths are not saved.
"""

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import struct
import sys
import winreg

HUB_CLASS = "{f18a0e88-c30c-11d0-8815-00a0c906bed8}"
GET_CONNECTION_EX = 0x220448
GET_CONNECTION_EX_V2 = 0x22045C


def inspect(vendor=0x8564, product=0x7000):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    root = rf"SYSTEM\CurrentControlSet\Control\DeviceClasses\{HUB_CLASS}"
    matches = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root) as devices:
        for number in range(winreg.QueryInfoKey(devices)[0]):
            name = winreg.EnumKey(devices, number)
            if not name.startswith("##?#"):
                continue
            device_path = "\\\\?\\" + name[4:]
            handle = kernel.CreateFileW(device_path, 0x40000000, 3, None, 3, 0, None)
            if handle == ctypes.c_void_p(-1).value:
                continue
            try:
                for port in range(1, 65):
                    buffer = ctypes.create_string_buffer(4096)
                    struct.pack_into("<I", buffer, 0, port)
                    returned = wintypes.DWORD()
                    if not kernel.DeviceIoControl(handle, GET_CONNECTION_EX,
                                                  buffer, len(buffer), buffer,
                                                  len(buffer), ctypes.byref(returned), None):
                        continue
                    raw = buffer.raw
                    vid, pid = struct.unpack_from("<HH", raw, 12)
                    if (vid, pid) != (vendor, product):
                        continue
                    bcd_usb = struct.unpack_from("<H", raw, 6)[0]
                    v2 = ctypes.create_string_buffer(struct.pack("<IIII", port, 16, 4, 0), 16)
                    succeeded = bool(kernel.DeviceIoControl(
                        handle, GET_CONNECTION_EX_V2, v2, 16, v2, 16,
                        ctypes.byref(returned), None))
                    flags = struct.unpack_from("<I", v2.raw, 12)[0] if succeeded else None
                    matches.append({
                        "vendor_id": f"{vid:04x}", "product_id": f"{pid:04x}",
                        "usb_descriptor_bcd": f"0x{bcd_usb:04x}",
                        "usb_specification": f"{bcd_usb >> 8}.{bcd_usb & 255:02x}",
                        "port": port, "speed_ex": raw[23],
                        "v2_query_succeeded": succeeded, "v2_flags": flags,
                        "operating_at_superspeed_or_higher": bool(flags & 1) if succeeded else None,
                        "operating_at_superspeed_plus_or_higher": bool(flags & 4) if succeeded else None,
                        "method": "Windows USB hub descriptor and EX_V2 read-only queries",
                    })
            finally:
                kernel.CloseHandle(handle)
    return {"matching_devices": matches}


if __name__ == "__main__":
    result = inspect()
    output = Path(__file__).resolve().parent / "results/usb_connection.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["matching_devices"]:
        sys.exit("The USB descriptor could not be verified.")
