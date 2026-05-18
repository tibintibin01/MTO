' 🏛️ MTO Treasury System - Silent Background Launcher
' Double-click this file to launch the system completely silently with ZERO black CMD windows or flashes!

Set WshShell = CreateObject("WScript.Shell")

' 1. Check if Docker is running using Run (returns exit code, prevents black window flash)
Dim dockerActive
dockerActive = WshShell.Run("cmd /c docker info", 0, True)

If dockerActive = 0 Then
    ' Docker is active! Start containers silently
    WshShell.Run "docker compose up -d", 0, True
Else
    ' Docker is not active. Fallback to native pythonw and npm run dev in hidden windows
    WshShell.Run "VENV\Scripts\pythonw.exe -m uvicorn backend.main:app --port 8001", 0, False
End If

' 2. Start Next.js Web Portal completely silently in a hidden window
WshShell.Run "cmd /c cd frontend && npm run dev", 0, False

' 3. Wait 6 seconds for background API & portal to warm up
WScript.Sleep 6000

' 4. Launch Cashier Desktop app using pythonw.exe to completely hide the background console window!
' This displays ONLY the modern clean GUI window with no black terminal behind it.
WshShell.Run "VENV\Scripts\pythonw.exe clients/desktop/main.py", 1, True

' 5. Clean Shutdown: Terminate background servers cleanly when the cashier closes the app!
' This prevents memory leaks and background processes from staying active after exiting.
If dockerActive <> 0 Then
    ' If we started native servers, shut them down cleanly
    WshShell.Run "taskkill /f /im pythonw.exe", 0, True
    WshShell.Run "taskkill /f /im node.exe", 0, True
End If
