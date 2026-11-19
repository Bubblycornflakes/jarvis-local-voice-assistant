#!/bin/zsh
# Builds Jarvis.app in /Applications (plus a Desktop shortcut). Re-run after moving the project.
set -e
cd "$(dirname "$0")"
PROJ="$PWD"
APP=/Applications/Jarvis.app

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# launcher: stays the parent process so macOS ties permissions to Jarvis.app
cat > "$APP/Contents/MacOS/Jarvis" <<EOF
#!/bin/zsh
cd "$PROJ"
pgrep -x ollama >/dev/null || /opt/homebrew/bin/ollama serve >/dev/null 2>&1 &
"$PROJ/.venv/bin/python" main.py >> data/run.log 2>&1
EOF
chmod +x "$APP/Contents/MacOS/Jarvis"

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Jarvis</string>
  <key>CFBundleDisplayName</key><string>Jarvis</string>
  <key>CFBundleIdentifier</key><string>com.example.jarvis</string>
  <key>CFBundleExecutable</key><string>Jarvis</string>
  <key>CFBundleIconFile</key><string>Jarvis</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>JARVIS listens for your voice commands.</string>
  <key>NSAppleEventsUsageDescription</key><string>JARVIS controls Music, Notes and Calendar for you.</string>
  <key>NSCalendarsUsageDescription</key><string>JARVIS reads your calendar to tell you what's on.</string>
</dict></plist>
EOF

.venv/bin/python make_icon.py data/Jarvis.iconset
iconutil -c icns data/Jarvis.iconset -o "$APP/Contents/Resources/Jarvis.icns"
codesign --force --deep -s - "$APP"

rm -rf ~/Desktop/Jarvis.app ~/Desktop/Jarvis
ln -s "$APP" ~/Desktop/Jarvis
echo "Built $APP"
