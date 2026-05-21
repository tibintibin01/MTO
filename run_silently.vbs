' 🏛️ MTO Treasury System - Silent Background Launcher
' Double-click this file to launch the system completely silently with ZERO black CMD windows or flashes!

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Guarantee that the current directory is always the script folder itself
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

' 1. Check if Docker is running using Run (returns exit code, prevents black window flash)
Dim dockerActive
dockerActive = WshShell.Run("cmd /c docker info", 0, True)

If dockerActive = 0 Then
    ' Docker is active! Start containers silently
    WshShell.Run "docker compose up -d", 0, True
Else
    ' Docker is not active. Fallback to native python.exe running in a HIDDEN window (style 0).
    ' We use python.exe (not pythonw.exe) here because uvicorn expects standard output streams
    ' to write logging information; window style 0 ensures it is 100% invisible with zero terminal windows.
    WshShell.Run "VENV\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8001", 0, False
End If

' 2. Start Next.js Web Portal completely silently in a hidden window
WshShell.Run "cmd /c cd frontend && npm run dev", 0, False

' 3. Wait 8 seconds for background API & portal to warm up (increased for high stability)
WScript.Sleep 8001

' 4. Launch Cashier Desktop app using pythonw.exe to completely hide the background console window!
' This displays ONLY the modern clean GUI window with no black terminal behind it.
WshShell.Run "VENV\Scripts\pythonw.exe clients/desktop/main.py", 1, True

' 5. Clean Shutdown: Terminate background servers cleanly when the cashier closes the app!
' This prevents memory leaks and background processes from staying active after exiting.
If dockerActive <> 0 Then
    ' If we started native servers, shut them down cleanly
    WshShell.Run "taskkill /f /im python.exe", 0, True
    WshShell.Run "taskkill /f /im pythonw.exe", 0, True
    WshShell.Run "taskkill /f /im node.exe", 0, True
End If
