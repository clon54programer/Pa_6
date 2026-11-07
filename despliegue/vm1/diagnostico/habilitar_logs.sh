#!/bin/bash
# Permite al usuario de laboratorio leer los logs del sistema (journal de
# systemd y /var/log) sin necesidad de root, agregándolo a los grupos
# `adm` y `systemd-journal` (los mismos que recomienda el propio journalctl).
set -eu
usermod -aG adm,systemd-journal vboxuser
echo "grupos de vboxuser:"
id vboxuser
echo
echo "Nota: el cambio aplica a sesiones SSH nuevas (las abiertas no lo ven)."
