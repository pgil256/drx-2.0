@echo off
echo Starting MCP Memory-Filesystem Server...
cd /d %~dp0
npm install
node index.js "C:/Users/user/Desktop/drx-2.1"
