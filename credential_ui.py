import tkinter as tk

from tkinter import messagebox

import os

import sys

from credentials import save_credentials


def open_credential_window():

    win=tk.Tk()

    win.title("Sophos Credentials")

    if getattr(sys,"frozen",False):

        base_path=getattr(sys,"_MEIPASS",os.path.dirname(sys.executable))

    else:

        base_path=os.path.dirname(os.path.abspath(__file__))


    icon_path=os.path.join(base_path,"assets","app.ico")

    try:

        win.iconbitmap(icon_path)

    except Exception:

        pass

    win.geometry("260x170")

    win.resizable(False,False)

    saved={"ok":False}


    tk.Label(win,text="Username").pack(pady=5)

    username=tk.Entry(win)

    username.pack()


    tk.Label(win,text="Password").pack(pady=5)

    password=tk.Entry(win,show="*")

    password.pack()


    def close():

        win.quit()

        win.destroy()


    def save():

        user_value=username.get().strip()

        pass_value=password.get().strip()

        if not user_value or not pass_value:

            messagebox.showerror("Missing Fields","Please enter both username and password")

            return


        try:

            save_credentials(user_value,pass_value)

            saved["ok"]=True

            messagebox.showinfo("Saved","Credentials saved securely")

            password.delete(0,tk.END)

            close()

        except Exception:

            messagebox.showerror("Save Failed","Could not save credentials. Please try again.")


    tk.Button(

    win,

    text="Save",

    command=save

    ).pack(pady=10)


    win.protocol(

    "WM_DELETE_WINDOW",

    close

    )


    win.mainloop()

    return saved["ok"]