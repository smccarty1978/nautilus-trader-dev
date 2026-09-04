@echo off
rem One command to launch a correctly identified Antigravity IDE writer session.
rem   scripts\launch_antigravity.cmd -Study <study_id>      open that study's worktree
rem   scripts\launch_antigravity.cmd -Path <folder>         open a folder
rem Sets NT_RESEARCH_AGENT=antigravity and a fresh NT_RESEARCH_AGENT_SESSION UUID for the launched instance.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_antigravity.ps1" %*
