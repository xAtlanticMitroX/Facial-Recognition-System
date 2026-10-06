"""
Run this to check what password is currently stored in the
machine-protected credential file, so you can compare it against your
actual Windows login password. Delete this file after checking - no
reason to leave a password-printing script lying around.
"""

from pathlib import Path
import win32crypt

CRED_FILE = Path("C:/ProgramData/FaceCredentialProvider/service_password.bin")

if not CRED_FILE.exists():
    print("No stored password file found.")
else:
    with open(CRED_FILE, "rb") as f:
        encrypted = f.read()
    decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)
    pw = decrypted[1].decode("utf-16-le")
    print(f"Stored password ({len(pw)} characters): {pw}")