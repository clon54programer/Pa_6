#!/bin/bash
# Pruebas unitarias del monitor en Linux, con el layout del repositorio
# (el proyecto espera `monitor.toml` en el directorio de trabajo).
set -u
rm -rf /opt/portocaribe-monitor/tests_monitor
cp -a /tmp/pa6-deploy/tests_monitor /opt/portocaribe-monitor/tests_monitor
find /opt/portocaribe-monitor/tests_monitor -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
install -m 0644 /tmp/modelo/monitor.toml /opt/portocaribe-monitor/monitor.toml
install -m 0644 /tmp/modelo/inventario.csv /opt/portocaribe-monitor/inventario.csv 2>/dev/null || true
cd /opt/portocaribe-monitor
python3 -m unittest discover -s tests_monitor -t . -v 2>&1 | tail -40
rm -rf /opt/portocaribe-monitor/tests_monitor
rm -f /opt/portocaribe-monitor/monitor.toml /opt/portocaribe-monitor/inventario.csv
