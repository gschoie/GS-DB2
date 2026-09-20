@echo off
rem 대상 앱(다올FI Pro 등)이 관리자 권한으로 실행 중이면
rem 이 파일로 longshot도 관리자 권한으로 띄워야 휠/키 입력이 전달됩니다.
powershell -Command "Start-Process -Verb RunAs -FilePath '%~dp0run.bat'"
