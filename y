#!/bin/bash
# Hilfsbefehl "ak": holt jeweils den neuesten Schritt von GitHub und fuehrt ihn aus.
cat > /usr/local/bin/ak <<'E'
#!/bin/bash
curl -fsSL "https://raw.githubusercontent.com/Vauplus69/abrechnungs-navi/anspruchskompass/schritt?$(date +%s)" | bash
E
chmod +x /usr/local/bin/ak
echo "Befehl ak eingerichtet."
ak
