' 🏛️ MTO Treasury System - Silent Background Launcher
' Double-click this file to launch the system completely silently without any messy black CMD windows!

Set WshShell = CreateObject("WScript.Shell")

' 1. Check if Docker is running
On Error Resume Next
Set objExec = WshShell.Exec("docker info")
Do While objExec.Status = 0
    WScript.Sleep 100
Loop

If objExec.ExitCode = 0 Then
    ' Docker is active! Start containers silently
    WshShell.Run "docker compose up -d", 0, True
Else
    ' Docker is not active. Fallback to native pythonw and npm run dev in hidden windows
    WshShell.Run "VENV\Scripts\pythonw.exe -m uvicorn backend.main:app --port 8001", 0, False
End If

' 2. Start Next.js Web Portal completely silently
WshShell.Run "cmd /c cd frontend && npm run dev", 0, False

' 3. Wait 6 seconds for background API & portal to warm up
WScript.Sleep 6000

' 4. Launch Cashier Desktop app normally (shows up on screen)
' The '1' parameter displays the window normally, and 'True' pauses this script until they close the app.
WshShell.Run "VENV\Scripts\python.exe clients/desktop/main.py", 1, True

' 5. Clean Shutdown: Terminate background servers cleanly when the cashier closes the app!
' This prevents memory leaks and background processes from staying active after exiting.
If objExec.ExitCode <> 0 Then
    ' If we started native servers, shut them down cleanly
    WshShell.Run "taskkill /f /im pythonw.exe", 0, True
    WshShell.Run "taskkill /f /im node.exe", 0, True
End If
