#!/usr/bin/env bash
# Instala lo necesario para generar los videos del curso.
set -euo pipefail
pip install -q kokoro-onnx soundfile imageio-ffmpeg playwright pillow openpyxl
TTS_DIR="${TTS_DIR:-/tmp/claude-0/tts}"
mkdir -p "$TTS_DIR"
R=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
[ -f "$TTS_DIR/kokoro-v1.0.int8.onnx" ] || curl -sSL -o "$TTS_DIR/kokoro-v1.0.int8.onnx" "$R/kokoro-v1.0.int8.onnx"
[ -f "$TTS_DIR/voices-v1.0.bin" ] || curl -sSL -o "$TTS_DIR/voices-v1.0.bin" "$R/voices-v1.0.bin"
echo "Listo. Modelo de voz en $TTS_DIR"
