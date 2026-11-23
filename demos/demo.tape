Output demos/hero.gif
Require python3

Set Shell "bash"
Set Theme "Dracula"
Set FontFamily "monospace"
Set FontSize 18
Set Width 1280
Set Height 480
Set Padding 26
Set Framerate 24
Set TypingSpeed 30ms
Env PYTHONIOENCODING "utf-8"

Sleep 400ms
Type "python3 scripts/replay_demo.py"
Enter
Wait+Screen /ERR_TYPE_MISMATCH/
Wait+Screen /QLEAN1 OK/
Sleep 3s
