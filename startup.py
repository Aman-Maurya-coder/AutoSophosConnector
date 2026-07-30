import winreg

import sys

import os


def add_to_startup():

    exe=sys.executable

    command_value='"'+exe+'"'

    key=winreg.OpenKey(

    winreg.HKEY_CURRENT_USER,

    r"Software\Microsoft\Windows\CurrentVersion\Run",

    0,

    winreg.KEY_SET_VALUE

    )


    try:

        current_value,_=winreg.QueryValueEx(key,"AutoSophosWifi")

        if current_value==command_value:

            winreg.CloseKey(key)

            return

    except FileNotFoundError:

        pass


    winreg.SetValueEx(

    key,

    "AutoSophosWifi",

    0,

    winreg.REG_SZ,

    command_value

    )


    winreg.CloseKey(key)