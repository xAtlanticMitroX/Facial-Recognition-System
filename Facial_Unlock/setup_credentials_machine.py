"""
Run this ONCE to store your Windows password in a machine-level
DPAPI-protected file, instead of Windows Credential Manager.

Why: Credential Manager entries are tied to a specific user's
interactive logon session in ways that don't reliably carry over to a
Windows Service running under that same account. CRYPTPROTECT_LOCAL_MACHINE
ties the encryption to the machine itself instead, so any process
running on this machine with sufficient privilege can decrypt it -
this sidesteps that whole class of problem.

Install dependency first:
    pip install pywin32
"""

import getpass
from pathlib import Path
import win32crypt
import win32cryptcon

CRED_DIR = Path("C:/ProgramData/FaceCredentialProvider")
CRED_FILE = CRED_DIR / "service_password.bin"


def main():
    pw = getpass.getpass("Enter your Windows password to store securely: ")
    if not pw:
        print("No password entered, aborting.")
        return

    CRED_DIR.mkdir(parents=True, exist_ok=True)

    encrypted = win32crypt.CryptProtectData(
        pw.encode("utf-16-le"), "face_unlock_service_password", None, None, None,
        win32cryptcon.CRYPTPROTECT_LOCAL_MACHINE
    )

    with open(CRED_FILE, "wb") as f:
        f.write(encrypted)

    print(f"Password stored (machine-protected) at {CRED_FILE}")


if __name__ == "__main__":
    main()
