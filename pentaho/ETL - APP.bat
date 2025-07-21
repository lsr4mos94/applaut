@echo off
 
TITLE ETL_APP
SET currentdir=%~dp0
SET kitchen=E:\BI\pentaho-data-integration\Kitchen.bat
SET logfile="%currentdir%log_app.txt"

echo. >> %logfile%
echo. >> %logfile%

"%kitchen%" /file:"%currentdir%job_app.kjb" /level:Basic >> %logfile%