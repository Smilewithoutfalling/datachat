"""Windows Job Object（阶段 2）：给沙箱子进程加内存上限、禁止再起子进程、禁剪贴板，关闭句柄即连带杀掉。

只用标准库 ctypes，不新增依赖。非 Windows 平台不导入本模块。
"""
import ctypes
from ctypes import wintypes

_JobObjectBasicUIRestrictions = 4
_JobObjectExtendedLimitInformation = 9

_LIMIT_ACTIVE_PROCESS = 0x00000008
_LIMIT_PROCESS_MEMORY = 0x00000100
_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_UILIMIT_ALL = 0x000000FF       # 桌面、显示设置、注销、全局原子、句柄、读/写剪贴板、系统参数


class _BASIC_LIMIT(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _EXTENDED_LIMIT(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BASIC_LIMIT),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _UI_RESTRICTIONS(ctypes.Structure):
    _fields_ = [("UIRestrictionsClass", wintypes.DWORD)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateJobObjectW.restype = wintypes.HANDLE
_k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
_k32.SetInformationJobObject.restype = wintypes.BOOL
_k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
_k32.AssignProcessToJobObject.restype = wintypes.BOOL
_k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
_k32.TerminateJobObject.restype = wintypes.BOOL
_k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
_k32.CloseHandle.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = [wintypes.HANDLE]


def _check(ok, what):
    if not ok:
        raise OSError(ctypes.get_last_error(), f"{what} 失败")


class Job:
    """with Job(mem_mb) as job: job.assign(popen)；退出 with 时关闭句柄，Job 里的进程全部被杀。"""

    def __init__(self, mem_mb: int | None):
        self.handle = _k32.CreateJobObjectW(None, None)
        _check(self.handle, "CreateJobObject")
        try:
            info = _EXTENDED_LIMIT()
            flags = _LIMIT_KILL_ON_JOB_CLOSE | _LIMIT_DIE_ON_UNHANDLED_EXCEPTION | _LIMIT_ACTIVE_PROCESS
            info.BasicLimitInformation.ActiveProcessLimit = 1
            if mem_mb:
                flags |= _LIMIT_PROCESS_MEMORY
                info.ProcessMemoryLimit = int(mem_mb) * 1024 * 1024
            info.BasicLimitInformation.LimitFlags = flags
            _check(_k32.SetInformationJobObject(self.handle, _JobObjectExtendedLimitInformation,
                                                ctypes.byref(info), ctypes.sizeof(info)),
                   "SetInformationJobObject(limits)")
            ui = _UI_RESTRICTIONS(_UILIMIT_ALL)
            _check(_k32.SetInformationJobObject(self.handle, _JobObjectBasicUIRestrictions,
                                                ctypes.byref(ui), ctypes.sizeof(ui)),
                   "SetInformationJobObject(ui)")
        except Exception:
            self.close()
            raise

    def assign(self, popen) -> None:
        _check(_k32.AssignProcessToJobObject(self.handle, int(popen._handle)), "AssignProcessToJobObject")

    def kill(self) -> None:
        if self.handle:
            _k32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            _k32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
