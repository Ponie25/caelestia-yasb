@echo off
setlocal
where cl.exe >nul 2>&1
if errorlevel 1 (
    echo Open an x64 Visual Studio developer command prompt with the Windows SDK installed.
    exit /b 1
)
if not defined WindowsSdkDir exit /b 1
if not defined WindowsSDKVersion exit /b 1
pushd "%~dp0"
cl /nologo /std:c++20 /O2 /EHsc /W3 /MT /LD /I "%WindowsSdkDir%Include\%WindowsSDKVersion%cppwinrt" lgwin.cpp /Fe:liquid_glass.dll user32.lib d3d11.lib dxgi.lib dcomp.lib dwmapi.lib d3dcompiler.lib windowsapp.lib
if errorlevel 1 (popd & exit /b 1)
copy /y liquid_glass.dll "..\..\config\dynamic-island\native\liquid_glass.dll" >nul
popd
exit /b 0
