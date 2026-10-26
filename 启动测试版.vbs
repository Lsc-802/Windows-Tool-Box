' Windows Tool Box - no-console launcher (VBS)
' Double-click this file to start the app with ZERO console window flash.
' (A .bat always flashes a cmd window briefly; a .vbs does not.)
Option Explicit

Dim fso, shell, scriptDir, pythonw, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = scriptDir

' Some environments inject PYTHONNOUSERSITE=1, which hides the user package
' folder (where psutil/wmi are installed). Remove it before starting Python.
On Error Resume Next
shell.Environment("PROCESS").Remove("PYTHONNOUSERSITE")
On Error GoTo 0

pythonw = "D:\Program Files\Python314\pythonw.exe"
If Not fso.FileExists(pythonw) Then
    pythonw = "pythonw.exe"
End If

cmd = """" & pythonw & """ ""main.py"""
' 0 = hide the window, False = do not wait for the app to exit
shell.Run cmd, 0, False
