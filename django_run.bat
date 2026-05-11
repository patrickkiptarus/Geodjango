@echo off
REM Django Nairobi Location Intelligence System - Windows Batch Script
REM This script helps run common Django commands

echo Nairobi Location Intelligence System - Django
echo ==============================================
echo.
echo Make sure you have:
echo 1. Python 3.8+ installed
echo 2. PostgreSQL with PostGIS extension
echo 3. Created virtual environment and installed requirements
echo.
echo Usage:
echo runserver    - Start development server
echo migrate      - Run database migrations
echo loaddata     - Load POI and ward data
echo shell        - Open Django shell
echo test         - Run test script
echo.
echo Example: django_run.bat runserver
echo.

if "%1"=="runserver" goto runserver
if "%1"=="migrate" goto migrate
if "%1"=="loaddata" goto loaddata
if "%1"=="shell" goto shell
if "%1"=="test" goto test

echo Invalid command. Use: runserver, migrate, loaddata, shell, or test
goto end

:runserver
echo Starting Django development server...
python manage.py runserver
goto end

:migrate
echo Running database migrations...
python manage.py migrate
goto end

:loaddata
echo Loading POI and ward data...
echo Make sure you have converted poi_nairobi.rds to CSV format first
python manage.py load_data --data-dir ../data
goto end

:shell
echo Opening Django shell...
python manage.py shell
goto end

:test
echo Running test script...
python test_setup.py
goto end

:end
echo.
echo Done.