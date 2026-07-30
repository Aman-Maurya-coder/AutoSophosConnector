import json

import os

import keyring


CONFIG_FILE="config.json"

SERVICE="AutoSophosWifi"

USERNAME_ACCOUNT="__username__"

PASSWORD_ACCOUNT="__password__"


def _safe_get(account):

    try:

        return keyring.get_password(SERVICE,account)

    except Exception:

        return None


def _safe_set(account,value):

    try:

        keyring.set_password(SERVICE,account,value)

        return True

    except Exception:

        return False


def _read_legacy_file():

    if not os.path.exists(CONFIG_FILE):

        return None,None


    try:

        with open(CONFIG_FILE,encoding="utf-8") as f:

            data=json.load(f)

    except Exception:

        return None,None


    username=data.get("username")

    password=data.get("password")

    return username,password


def _scrub_legacy_file():

    if not os.path.exists(CONFIG_FILE):

        return


    try:

        with open(CONFIG_FILE,"w",encoding="utf-8") as f:

            json.dump({},f)

    except Exception:

        pass


def _migrate_legacy_storage():

    legacy_username,legacy_password=_read_legacy_file()

    if not legacy_username:

        return


    old_keyring_password=_safe_get(legacy_username)

    password_to_store=legacy_password or old_keyring_password

    if not password_to_store:

        return


    if _safe_set(USERNAME_ACCOUNT,legacy_username) and _safe_set(PASSWORD_ACCOUNT,password_to_store):

        _scrub_legacy_file()


def load_credentials():

    username=_safe_get(USERNAME_ACCOUNT)

    password=_safe_get(PASSWORD_ACCOUNT)

    if username and password:

        return username,password


    _migrate_legacy_storage()


    username=_safe_get(USERNAME_ACCOUNT)

    password=_safe_get(PASSWORD_ACCOUNT)

    if not username or not password:

        return None,None


    return username,password


def save_credentials(username,password):

    username=(username or "").strip()

    password=(password or "").strip()

    if not username or not password:

        raise ValueError("Username and password are required")


    username_saved=_safe_set(USERNAME_ACCOUNT,username)

    password_saved=_safe_set(PASSWORD_ACCOUNT,password)

    if not username_saved or not password_saved:

        raise RuntimeError("Failed to save credentials in keyring")


    _scrub_legacy_file()