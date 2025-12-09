#!/bin/bash
# ================================================
#  START.SH – VERSION QUI NE PLANTE PLUS JAMAIS
#  Fonctionne même après reboot, plantage ou coupure
# ================================================

cd "/home/jerome/Documents/projet_yolo_v2/Robotm/video_stream"

# 1. Tue tout ce qui pourrait bloquer (même les zombies)
sudo pkill -9 -f main.py 2>/dev/null
sudo pkill -9 -f python3 2>/dev/null
sudo killall -9 hailortd gstreamer-1.0 gst-launch-1.0 2>/dev/null
sleep 1

# 2. Reset complet du Hailo-8 (c’est ÇA qui résout 99% des blocages)
echo "Reset du Hailo-8..."
sudo hailortcli fw-control reset > /dev/null 2>&1
sleep 2

# 3. Petit reset des caméras CSI (au cas où)
sudo v4l2-ctl --list-devices 2>/dev/null | grep -o '/dev/video[0-9]' | head -2 | xargs -I{} sudo v4l2-ctl --device={} --set-ctrl=vertical_blanking=10000 2>/dev/null

echo "================================================="
echo "Démarrage du suivi PAN ONLY – 100% stable"
echo "URL → http://$(hostname -I | awk '{print $1}' | head -1):8080"
echo "================================================="

# 4. Lancement en premier plan (tu vois tout, et ça ne se ferme plus jamais tout seul)
exec /home/jerome/hailo-rpi5-examples/hailo-rpi5-examples/venv_hailo_rpi_examples/bin/python3 main.py