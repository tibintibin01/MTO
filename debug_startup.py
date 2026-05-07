
import sys
import traceback

def test_startup():
    print("Testing imports...")
    try:
        import customtkinter as ctk
        print(f"customtkinter version: {ctk.__version__}")
        import PIL
        print(f"Pillow version: {PIL.__version__}")
        import matplotlib
        print(f"Matplotlib version: {matplotlib.__version__}")
        import darkdetect
        print("darkdetect imported successfully")
    except Exception as e:
        print(f"IMPORT ERROR: {e}")
        traceback.print_exc()
        return

    print("\nTesting CTK Initialization...")
    try:
        root = ctk.CTk()
        root.withdraw() # Don't show the window
        print("ctk.CTk() initialized successfully")
        root.destroy()
    except Exception as e:
        print(f"INITIALIZATION ERROR: {e}")
        traceback.print_exc()
        return

    print("\nSUCCESS: All core components initialized correctly.")

if __name__ == "__main__":
    test_startup()
