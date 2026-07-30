import ctypes
from ctypes import wintypes
import platform

_IS_WINDOWS = platform.system() == "Windows"

if _IS_WINDOWS:
    wlanapi = ctypes.windll.wlanapi
    _iphlpapi = ctypes.windll.iphlpapi
else:
    wlanapi = None
    _iphlpapi = None

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8)
    ]

class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [
        ("InterfaceGuid", GUID),
        ("strInterfaceDescription", ctypes.c_wchar * 256),
        ("isState", ctypes.c_uint)
    ]

class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", ctypes.c_ulong),
        ("dwIndex", ctypes.c_ulong),
        ("InterfaceInfo", WLAN_INTERFACE_INFO * 1)
    ]

class DOT11_SSID(ctypes.Structure):
    _fields_ = [
        ("uSSIDLength", ctypes.c_ulong),
        ("ucSSID", ctypes.c_char * 32)
    ]

class WLAN_AVAILABLE_NETWORK(ctypes.Structure):
    _fields_ = [
        ("strProfileName", ctypes.c_wchar * 256),
        ("dot11Ssid", DOT11_SSID),
        ("dot11BssType", ctypes.c_uint),
        ("uNumberOfBssids", ctypes.c_ulong),
        ("bNetworkConnectable", ctypes.c_bool),
        ("wlanNotConnectableReason", ctypes.c_uint),
        ("uNumberOfPhyTypes", ctypes.c_ulong),
        ("dot11PhyTypes", ctypes.c_uint * 8),
        ("bMorePhyTypes", ctypes.c_bool),
        ("wlanSignalQuality", ctypes.c_ulong),
        ("bSecurityEnabled", ctypes.c_bool),
        ("dot11DefaultAuthAlgorithm", ctypes.c_uint),
        ("dot11DefaultCipherAlgorithm", ctypes.c_uint),
        ("dwFlags", ctypes.c_ulong),
        ("dwReserved", ctypes.c_ulong)
    ]

class WLAN_AVAILABLE_NETWORK_LIST(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", ctypes.c_ulong),
        ("dwIndex", ctypes.c_ulong),
        ("Network", WLAN_AVAILABLE_NETWORK * 1)
    ]

class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("dot11Ssid", DOT11_SSID),
        ("dot11BssType", ctypes.c_uint),
        ("dot11Bssid", ctypes.c_ubyte * 6),
        ("dot11PhyType", ctypes.c_uint),
        ("uDot11PhyIndex", ctypes.c_ulong),
        ("wlanSignalQuality", ctypes.c_ulong),
        ("ulRxRate", ctypes.c_ulong),
        ("ulTxRate", ctypes.c_ulong)
    ]

class WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("bSecurityEnabled", ctypes.c_bool),
        ("bOneXEnabled", ctypes.c_bool),
        ("dot11AuthAlgorithm", ctypes.c_uint),
        ("dot11CipherAlgorithm", ctypes.c_uint)
    ]

class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("isState", ctypes.c_uint),
        ("wlanConnectionMode", ctypes.c_uint),
        ("strProfileName", ctypes.c_wchar * 256),
        ("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
        ("wlanSecurityAttributes", WLAN_SECURITY_ATTRIBUTES)
    ]

def get_wifi_info():
    if not wlanapi:
        return None, []
        
    client_handle = wintypes.HANDLE()
    negotiated_version = wintypes.DWORD()
    
    res = wlanapi.WlanOpenHandle(2, None, ctypes.byref(negotiated_version), ctypes.byref(client_handle))
    if res != 0:
        return None, []
        
    try:
        p_interface_list = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
        res = wlanapi.WlanEnumInterfaces(client_handle, None, ctypes.byref(p_interface_list))
        if res != 0:
            return None, []
            
        try:
            if p_interface_list.contents.dwNumberOfItems == 0:
                return None, []
                
            interface_info = ctypes.cast(
                ctypes.addressof(p_interface_list.contents.InterfaceInfo),
                ctypes.POINTER(WLAN_INTERFACE_INFO)
            ).contents
            
            guid = interface_info.InterfaceGuid
            
            p_data = ctypes.c_void_p()
            data_size = wintypes.DWORD()
            res = wlanapi.WlanQueryInterface(
                client_handle, 
                ctypes.byref(guid), 
                7, # wlan_intf_opcode_current_connection
                None, 
                ctypes.byref(data_size), 
                ctypes.byref(p_data),
                None
            )
            
            current_ssid = None
            if res == 0:
                conn_attr = ctypes.cast(p_data, ctypes.POINTER(WLAN_CONNECTION_ATTRIBUTES)).contents
                ssid_struct = conn_attr.wlanAssociationAttributes.dot11Ssid
                if ssid_struct.uSSIDLength > 0:
                    current_ssid = ssid_struct.ucSSID[:ssid_struct.uSSIDLength].decode('utf-8', errors='ignore')
                wlanapi.WlanFreeMemory(p_data)
                
            return current_ssid, []
            
        finally:
            wlanapi.WlanFreeMemory(p_interface_list)
            
    finally:
        wlanapi.WlanCloseHandle(client_handle, None)


# ---------------------------------------------------------------------------
# Gateway-IP detection via GetAdaptersInfo (iphlpapi)
# This API reads IP configuration only — no SSID access, no location trigger.
# ---------------------------------------------------------------------------

_MAX_ADAPTER_NAME  = 260
_MAX_ADAPTER_DESC  = 128
_MAX_ADAPTER_ADDR  = 8


class _IP_ADDR_STRING(ctypes.Structure):
    pass

_IP_ADDR_STRING._fields_ = [
    ("Next",      ctypes.POINTER(_IP_ADDR_STRING)),
    ("IpAddress", ctypes.c_char * 16),
    ("IpMask",    ctypes.c_char * 16),
    ("Context",   ctypes.c_ulong),
]


class _IP_ADAPTER_INFO(ctypes.Structure):
    pass

_IP_ADAPTER_INFO._fields_ = [
    ("Next",               ctypes.POINTER(_IP_ADAPTER_INFO)),
    ("ComboIndex",         ctypes.c_ulong),
    ("AdapterName",        ctypes.c_char * (_MAX_ADAPTER_NAME + 4)),
    ("Description",        ctypes.c_char * (_MAX_ADAPTER_DESC  + 4)),
    ("AddressLength",      ctypes.c_uint),
    ("Address",            ctypes.c_ubyte * _MAX_ADAPTER_ADDR),
    ("Index",              ctypes.c_ulong),
    ("Type",               ctypes.c_uint),
    ("DhcpEnabled",        ctypes.c_uint),
    ("CurrentIpAddress",   ctypes.POINTER(_IP_ADDR_STRING)),
    ("IpAddressList",      _IP_ADDR_STRING),
    ("GatewayList",        _IP_ADDR_STRING),
    ("DhcpServer",         _IP_ADDR_STRING),
    ("HaveWins",           ctypes.c_bool),
    ("PrimaryWinsServer",  _IP_ADDR_STRING),
    ("SecondaryWinsServer",_IP_ADDR_STRING),
    ("LeaseObtained",      ctypes.c_long),
    ("LeaseExpires",       ctypes.c_long),
]

_ERROR_BUFFER_OVERFLOW = 111


def get_gateway_ips():
    """Return a set of gateway IP strings from all active network adapters.

    Uses GetAdaptersInfo (iphlpapi.dll) which queries IP-layer configuration
    only.  It never reads the Wi-Fi SSID and therefore never triggers the
    Windows location-access indicator.

    Returns an empty set on non-Windows or on any API failure.
    """
    if not _IS_WINDOWS or not _iphlpapi:
        return set()

    buf_len = ctypes.c_ulong(15_000)
    buf = ctypes.create_string_buffer(buf_len.value)

    ret = _iphlpapi.GetAdaptersInfo(buf, ctypes.byref(buf_len))
    if ret == _ERROR_BUFFER_OVERFLOW:
        buf = ctypes.create_string_buffer(buf_len.value)
        ret = _iphlpapi.GetAdaptersInfo(buf, ctypes.byref(buf_len))

    if ret != 0:
        return set()

    gateways: set[str] = set()
    try:
        adapter = ctypes.cast(buf, ctypes.POINTER(_IP_ADAPTER_INFO)).contents
        while True:
            gw = (
                adapter.GatewayList.IpAddress
                .decode("ascii", errors="ignore")
                .strip("\x00")
                .strip()
            )
            if gw and gw != "0.0.0.0":
                gateways.add(gw)
            if not adapter.Next:
                break
            adapter = adapter.Next.contents
    except Exception:
        pass

    return gateways
