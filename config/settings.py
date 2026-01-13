"""
Configuration du système
"""

import os
from dataclasses import dataclass

@dataclass
class WebConfig:
    """Configuration Web"""
    host: str = "0.0.0.0"
    port: int = 8080
    stream_fps: int = 30
    jpeg_quality: int = 80

@dataclass
class RecordingConfig:
    """Configuration Enregistrement"""
    fps: int = 20  
    resolution: tuple = (1920, 1080)  
    codec: str = "mp4v"
    file_extension: str = ".mp4"
    output_dir: str = "enregistrements"

@dataclass
class HailoConfig:
    """Configuration Hailo/Détection"""
    input_source: str = 'rpi:0'  
    hef_path: str = '/home/jerome/Documents/projet_yolo_v2/yolo_models/yolo11m.hef'
    frame_skip: int = 2

@dataclass
class ServoConfig:
    """Configuration Servo (PTZ)"""
    pan_channel: int = 0         # Canal pour le mouvement horizontal (Pan)
    tilt_channel: int = 1        # Canal pour le mouvement vertical (Tilt)
    min_angle: int = 20
    max_angle: int = 160
    fixed_tilt_angle: int = 120  # Angle de base pour le tilt

    # PARAMÈTRES POUR UN SUIVI INTELLIGENT 
    
    target_lost_wait_duration: float = 2.0  
    return_to_center_speed: float = 0.005  
    
    #Facteur de lissage de la position de la cible (quand elle est détectée).
    target_smoothing_factor: float = 0.08  
    
    # [VITESSE] Seuil en pixels (sur 640px) pour différencier un mouvement court d'un mouvement long.
    slow_move_threshold_pixels: int = 40 
    
    # [VITESSE] Vitesse pour les mouvements courts (déplacement subtil).
    slow_smoothing_factor: float = 0.08
    
    # [VITESSE] Vitesse maximale pour les longs déplacements (suivi réactif).
    fast_smoothing_factor: float = 0.25
    pan_offset_right: float = -5.0
    pan_offset_left: float = 10.0

@dataclass
class ZoomConfig:
    """Configuration Zoom"""
    max_zoom: float = 1.0
    min_zoom: float = 1.0

class Config:
    """Classe principale de configuration"""
    
    def __init__(self):
        self.web = WebConfig()
        self.recording = RecordingConfig()
        self.hailo = HailoConfig()
        self.servo = ServoConfig()
        self.zoom = ZoomConfig()
        
        self._create_directories()
    
    def _create_directories(self):
        """Crée les répertoires nécessaires"""
        os.makedirs(self.recording.output_dir, exist_ok=True)
    
    def get_server_url(self):
        """Retourne l'URL du serveur"""
        return f"http://{self.get_server_ip()}:{self.web.port}"
    
    @staticmethod
    def get_server_ip():
        """Récupère l'IP du serveur (à adapter)"""
        return "127.0.0.1"