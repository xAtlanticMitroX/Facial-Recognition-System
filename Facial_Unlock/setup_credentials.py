"""
Run this ONCE to store your Windows password securely in Windows
Credential Manager (via the `keyring` library), instead of hardcoding
it in a script.

Install dependency first:
    pip install keyring
"""

import getpass
import keyring

SERVICE_NAME = "facial_unlock"
KEYRING_USERNAME = "facial_unlock_user"


def main():
    pw = getpass.getpass("Enter your Windows password to store securely: ")
    if not pw:
        print("No password entered, aborting.")
        return
    keyring.set_password(SERVICE_NAME, KEYRING_USERNAME, pw)
    print("Password stored in Windows Credential Manager under "
          f"service='{SERVICE_NAME}'.")
    print("You can verify/remove it later via Control Panel > "
          "Credential Manager > Windows Credentials.")


if __name__ == "__main__":
    main()
