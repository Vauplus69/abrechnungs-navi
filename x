#!/bin/bash
# Holt die neuen AnspruchsKompass-Dateien und legt sie als Vorschau ab.
set -e
T=$(mktemp -d)
curl -fsSL https://codeload.github.com/Vauplus69/abrechnungs-navi/tar.gz/anspruchskompass | tar xz -C "$T" --strip-components=1
bash "$T/ak.sh" 2>&1 | tee /root/ak-ergebnis.txt
