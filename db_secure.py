import sys
import uuid
import base64
import json
import os
from cryptography.fernet import Fernet

def get_machine_key():
    machine_id = str(uuid.getnode()).encode().ljust(32)[:32]
    return base64.urlsafe_b64encode(machine_id)

def encrypt_password(password):
    f = Fernet(get_machine_key())
    return f.encrypt(password.encode()).decode()

def main():
    print("MTO Database Security Utility")
    print("==============================")
    
    if len(sys.argv) > 1 and sys.argv[1] == "--seal":
        config_path = "db_config.json"
        if not os.path.exists(config_path):
            print(f"Error: {config_path} not found.")
            return
            
        with open(config_path, "r") as f:
            config = json.load(f)
            
        modified = False
        # Check both runtime and maintenance sections
        for section_name in ["runtime", "maintenance"]:
            if section_name in config:
                section = config[section_name]
            elif section_name == "runtime": # Root level fallback
                section = config
            else:
                continue
                
            if "password" in section and section["password"]:
                print(f"Sealing '{section_name}' password...")
                section["password_encrypted"] = encrypt_password(section["password"])
                del section["password"]
                modified = True
        
        if modified:
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            print("\nSuccessfully sealed db_config.json. Plaintext passwords removed.")
        else:
            print("\nNo plaintext passwords found to seal (or passwords are empty).")
    else:
        password = input("Enter database password to encrypt: ")
        if not password:
            print("Password cannot be empty.")
            return
        encrypted = encrypt_password(password)
        print("\nEncrypted Token (Machine-Specific):")
        print(encrypted)
        print("\nYou can add this to db_config.json as 'password_encrypted' and remove 'password'.")

if __name__ == "__main__":
    main()
