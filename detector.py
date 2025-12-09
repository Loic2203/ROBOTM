"""
Module de détection Hailo (sur caméra fixe) 
"""

import time
import threading
import cv2
import numpy as np
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import hailo
import math

# Imports SDK Hailo
from hailo_apps.hailo_app_python.core.common.core import get_default_parser
from hailo_apps.hailo_app_python.core.common.buffer_utils import get_caps_from_pad, get_numpy_from_buffer
from hailo_apps.hailo_app_python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.hailo_app_python.apps.detection.detection_pipeline import GStreamerDetectionApp


# Classe de données utilisateur pour l'application SDK (Contient l'instance du détecteur)
class HailoUserData(app_callback_class):
    def __init__(self, detector_instance):
        super().__init__()
        self.detector = detector_instance
        self.frame_skip = detector_instance.config.hailo.frame_skip


class HailoDetector:
    def __init__(self, config):
        self.config = config
        self.current_app = None
        self.user_data = None
        self.running = False
        self.detection_thread = None
        
        # Définition de la résolution d'entrée du modèle HEF (typique pour Hailo)
        self.HEF_WIDTH = 640
        self.HEF_HEIGHT = 640
        
        # États de détection (partagés)
        self.person_centers = []
        self.ball_center = None
        self.target_center = (self.HEF_WIDTH // 2, self.HEF_HEIGHT // 2)
        self.mode_text = "Pas de détection"
        self.frame_width = self.HEF_WIDTH
        
        # Verrou
        self.detection_lock = threading.Lock()

    def _setup_parser(self):
        """Configure le parser pour l'application SDK en mode background."""
        parser = get_default_parser()
        parser.set_defaults(
            # CLÉ: Spécifie explicitement l'index 0 pour la caméra fixe afin d'éviter le conflit CameraManager
            input='rpi:0',          
            hef_path=self.config.hailo.hef_path,
            use_frame=False,      # Pas de frame en sortie du pipeline (mode headless)
            show_fps=False,       # Désactive l'affichage FPS de l'SDK
            disable_overlay=True  # Désactive le dessin de l'overlay par l'SDK
        )
        return parser

    def start(self):
        """Démarre la détection en arrière-plan sur la caméra fixe via l'SDK Hailo."""
        print("🎯 Démarrage du détecteur Hailo en mode background sur Caméra Fixe (Index 0)...")

        # 1. Préparation du parser
        parser = self._setup_parser()
        args = parser.parse_args([])

        # 2. Création de l'instance d'application SDK
        self.user_data = HailoUserData(self) 
        self.current_app = GStreamerDetectionApp(self.app_callback, self.user_data, parser)
        
        # 3. Lancement dans un thread
        self.running = True
        self.detection_thread = threading.Thread(target=self._run_detection_app, daemon=True)
        self.detection_thread.start()
        print("✅ Détection Hailo démarrée en arrière-plan (sans fenêtre).")

    def _run_detection_app(self):
        """Fonction cible pour le thread de l'application Hailo."""
        try:
            self.current_app.run()
        except Exception as e:
            print(f"❌ Erreur d'exécution HailoApp: {e}")
            self.running = False

    def stop(self):
        """Arrête l'application Hailo."""
        if self.current_app:
            try:
                self.current_app.stop()
                print("🛑 Détecteur Hailo arrêté.")
            except Exception as e:
                print(f"⚠️ Erreur lors de l'arrêt de HailoApp: {e}")
            
            self.running = False
            if self.detection_thread and self.detection_thread.is_alive():
                self.detection_thread.join(timeout=1)
    
    # --- Callback de l'SDK ---
    def app_callback(self, pad, info, user_data):
        """Callback appelé par l'application SDK (tourne dans le thread GStreamer)."""
        
        user_data.increment()
        
        if user_data.get_count() % self.config.hailo.frame_skip != 0:
            return Gst.PadProbeReturn.OK
        
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK

        roi = hailo.get_roi_from_buffer(buffer)
        detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
        
        with self.detection_lock:
            self.person_centers = []
            self.ball_center = None
            
            for detection in detections:
                label, _, _, _, cx_norm, cy_norm = self._extract_detection_info_norm(detection)
                
                # Conversion des coordonnées normalisées [0, 1] en coordonnées HEF (640x640)
                cx = int(cx_norm * self.HEF_WIDTH)
                cy = int(cy_norm * self.HEF_HEIGHT)
                
                if label == "person":
                    self.person_centers.append((cx, cy))
                elif label == "sports ball":
                    self.ball_center = (cx, cy)
            
            self._calculate_target_center()

        return Gst.PadProbeReturn.OK

    def _extract_detection_info_norm(self, detection):
        """Extrait les infos de détection en coordonnées normalisées [0, 1]."""
        label = detection.get_label()
        bbox = detection.get_bbox()
        confidence = detection.get_confidence()
        
        track_id = 0
        track = detection.get_objects_typed(hailo.HAILO_UNIQUE_ID)
        if len(track) == 1:
            track_id = track[0].get_id()
        
        cx_norm = (bbox.xmin() + bbox.xmax()) / 2
        cy_norm = (bbox.ymin() + bbox.ymax()) / 2
        
        return label, bbox, confidence, track_id, cx_norm, cy_norm

    def _find_closest_person(self):
        if not self.ball_center:
            return None
        
        bx, by = self.ball_center
        min_dist, closest = float('inf'), None
        
        for px, py in self.person_centers:
            dist = math.sqrt((px - bx)**2 + (py - by)**2)
            if dist < 100 and dist < min_dist:
                min_dist, closest = dist, (px, py)
        
        return closest
    
    def _calculate_target_center(self):
        """Calcule le centre cible pour le suivi (dans la résolution HEF)."""
        closest = self._find_closest_person()
        if closest:
            self.target_center = closest
            self.mode_text = "Suivi joueur avec ballon"
        elif self.ball_center:
            self.target_center = self.ball_center
            self.mode_text = "Suivi ballon seul"
        elif self.person_centers:
            self.target_center = (\
                sum(x for x, y in self.person_centers) // len(self.person_centers),\
                sum(y for x, y in self.person_centers) // len(self.person_centers)\
            )
            self.mode_text = "Suivi moyenne des joueurs"
        else:
            self.target_center = (self.HEF_WIDTH // 2, self.HEF_HEIGHT // 2)
            self.mode_text = "Pas de détection"
    
    def get_detection_status(self):
        """Retourne le statut de détection pour main.py."""
        with self.detection_lock:
            return {
                'person_count': len(self.person_centers),
                'ball_detected': self.ball_center is not None,
                'mode': self.mode_text,
                'target_center': self.target_center,
                'hef_resolution': (self.HEF_WIDTH, self.HEF_HEIGHT)
            }
