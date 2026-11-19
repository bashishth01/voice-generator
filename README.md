# Voice Generator

Turn text into voice (mp3) using free Microsoft voices. Two modes: **Standalone** (one narrator) and **Conversation** (up to 4 speakers).

## Run
Double-click **start.bat**. First run it will:
1. Check for Python – if missing, it asks whether to install it (uses winget). Answer N and it stops with an error.
2. Create a private environment and install `edge-tts`.
3. Ask whether to install ffmpeg (needed for pauses and joining conversation lines).
4. Open the app at http://localhost:8765

Needs an internet connection (voices come from Microsoft's online service).

## Conversation format
```
A: Hi! Did you finish the practice test?
B: Yes, I scored seven in listening!
```
Pick a voice, speed and pitch for each speaker (A–D).

## Pauses and expression
| Markup | Meaning |
|---|---|
| `<break time="500ms"/>` or `<break time="1.5s"/>` | silent pause |
| `<prosody rate="+20%">text</prosody>` | speak that part faster (`-20%` slower). Words: `x-slow slow fast x-fast` |
| `<prosody pitch="+10Hz">text</prosody>` | higher pitch (`-10Hz` lower). Words: `low high` |
| `<prosody volume="+20%">text</prosody>` | louder (`-20%` softer). Words: `soft loud` |
| `<emphasis>text</emphasis>` | slightly slower and louder |

Combine them: `<prosody rate="slow" pitch="low" volume="soft">whisper-like line</prosody>`.
Tags add on top of the speaker's own sliders. In the app, select text and click the buttons above the text box.

Example:
```
A: This is <emphasis>really</emphasis> important.<break time="700ms"/> Listen carefully.
B: <prosody rate="fast">Okay, okay!</prosody><break time="1s"/> I understand now.
```
