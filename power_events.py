import ctypes
import ctypes.wintypes
import threading


WM_POWERBROADCAST=0x0218
PBT_APMRESUMEAUTOMATIC=0x0012
PBT_APMRESUMESUSPEND=0x0007


class PowerEventListener:


    def __init__(self,on_resume):

        self.on_resume=on_resume

        self.thread=None

        self.running=False

        self.window_handle=None

        self._class_name="AutoSophosPowerListener"


    def start(self):

        if self.thread and self.thread.is_alive():

            return


        self.running=True

        self.thread=threading.Thread(target=self._message_loop,daemon=True)

        self.thread.start()


    def stop(self):

        self.running=False

        if self.window_handle:

            ctypes.windll.user32.PostMessageW(self.window_handle,0x0010,0,0)


    def _message_loop(self):

        if not hasattr(ctypes,"windll"):

            return


        wnd_proc_type=ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_void_p
        )


        def wnd_proc(hwnd,msg,wparam,lparam):

            if msg==WM_POWERBROADCAST and wparam in {PBT_APMRESUMEAUTOMATIC,PBT_APMRESUMESUSPEND}:

                try:

                    self.on_resume()

                except Exception:

                    pass

                return 1


            return ctypes.windll.user32.DefWindowProcW(hwnd,msg,wparam,lparam)


        self._wnd_proc=wnd_proc_type(wnd_proc)

        hinstance=ctypes.windll.kernel32.GetModuleHandleW(None)

        class_name=ctypes.c_wchar_p(self._class_name)


        class WNDCLASS(ctypes.Structure):

            _fields_=[
                ("style",ctypes.c_uint),
                ("lpfnWndProc",wnd_proc_type),
                ("cbClsExtra",ctypes.c_int),
                ("cbWndExtra",ctypes.c_int),
                ("hInstance",ctypes.c_void_p),
                ("hIcon",ctypes.c_void_p),
                ("hCursor",ctypes.c_void_p),
                ("hbrBackground",ctypes.c_void_p),
                ("lpszMenuName",ctypes.c_wchar_p),
                ("lpszClassName",ctypes.c_wchar_p),
            ]


        wnd_class=WNDCLASS()
        wnd_class.lpfnWndProc=self._wnd_proc
        wnd_class.lpszClassName=class_name
        wnd_class.hInstance=hinstance


        atom=ctypes.windll.user32.RegisterClassW(ctypes.byref(wnd_class))
        if not atom:
            return


        hwnd=ctypes.windll.user32.CreateWindowExW(
            0,
            class_name,
            class_name,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            hinstance,
            0
        )

        if not hwnd:
            ctypes.windll.user32.UnregisterClassW(class_name,hinstance)
            return


        self.window_handle=hwnd

        msg=ctypes.wintypes.MSG()
        while self.running and ctypes.windll.user32.GetMessageW(ctypes.byref(msg),0,0,0)!=0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))


        ctypes.windll.user32.DestroyWindow(hwnd)
        ctypes.windll.user32.UnregisterClassW(class_name,hinstance)
