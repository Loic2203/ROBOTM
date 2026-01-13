"""
Module de détection Hailo (sur caméra fixe) 
Ce module est le "cerveau IA" du système. Il s'exécute en arrière-plan,
analyse le flux de la caméra fixe (Caméra 0) avec la puce Hailo,
et détermine quelle est la cible la plus pertinente à suivre.
"""

import time
import threading
import math
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import hailo
# Outils du SDK Hailo pour construire et gérer l'application de détection
from hailo_apps.hailo_app_python.core.common.core import get_default_parser
from hailo_apps.hailo_app_python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.hailo_app_python.apps.detection.detection_pipeline import GStreamerDetectionApp


# ---CLASSE UTILITAIRE POUR LE SDK HAILO ---
# Le SDK Hailo a besoin d'une classe spécifique pour passer des données utilisateur
# à sa fonction de callback. On l'utilise pour donner accès à notre instance HailoDetector.
class HailoUserData(app_callback_class):
    def __init__(self, detector_instance):
        super().__init__()
        self.detector = detector_instance
        self.frame_skip = detector_instance.config.hailo.frame_skip

# ---DÉFINITION DE LA CLASSE PRINCIPALE ---
class HailoDetector:
    # ---MÉTHODE __init__ (Le Plan de Construction) ---
    def __init__(self, config):
        self.config = config # Référence vers la configuration générale
        self.current_app = None # L'objet de l'application SDK Hailo
        self.user_data = None # L'objet qui fait le pont avec le SDK
        self.running = False # Drapeau pour contrôler le thread de détection
        self.detection_thread = None # Le thread qui fera tourner la détection
        
        # Dimensions de l'image sur laquelle le modèle d'IA a été entraîné.
        self.HEF_WIDTH = 640
        self.HEF_HEIGHT = 640
        
        # ===================================================================
        # VARIABLES D'ÉTAT PARTAGÉES (le "rapport de situation" de l'IA)
        # ===================================================================
        self.person_centers = [] # Liste des positions des personnes détectées
        self.ball_center = None # Position du ballon (s'il est détecté)
        self.target_center = (self.HEF_WIDTH // 2, self.HEF_HEIGHT // 2) # La cible finale à suivre
        self.mode_text = "Pas de détection" 
        # ===================================================================
        
        # Verrou pour protéger l'accès à ces variables partagées,
        # car elles sont écrites par ce thread et lues par le thread principal (main.py).
        self.detection_lock = threading.Lock()

    # ---MÉTHODES DE GESTION DU CYCLE DE VIE ---

    # Prépare les arguments pour lancer l'application du SDK Hailo en mode "headless".
    def _setup_parser(self):
        parser = get_default_parser()
        parser.set_defaults(
            #Utilisation de la caméra à l'index 0.
            input='rpi:0',          
            # Chemin vers le modèle d'IA compilé (.hef).
            hef_path=self.config.hailo.hef_path,
            # Optimisations pour tourner en arrière-plan sans affichage :
            use_frame=False,      # Ne pas préparer d'image en sortie
            show_fps=False,       # Ne pas calculer/afficher le FPS
            disable_overlay=True  # Ne pas dessiner les boîtes de détection sur une image
        )
        return parser

    # Démarre tout le processus de détection dans un thread séparé.
    def start(self):
        print("🎯 Démarrage du détecteur Hailo en mode background sur Caméra Fixe (Index 0)...")

        parser = self._setup_parser()
        args = parser.parse_args([]) # On passe une liste vide car les args sont définis par set_defaults

        # On crée l'application du SDK en lui passant notre fonction de callback 'app_callback'.
        self.user_data = HailoUserData(self) 
        self.current_app = GStreamerDetectionApp(self.app_callback, self.user_data, parser)
        
        # On lance l'application dans un thread pour ne pas bloquer le programme principal.
        self.running = True
        self.detection_thread = threading.Thread(target=self._run_detection_app, daemon=True)
        self.detection_thread.start()
        print("✅ Détection Hailo démarrée en arrière-plan.")

    # Fonction cible du thread, qui ne fait qu'exécuter l'application Hailo.
    def _run_detection_app(self):
        try:
            self.current_app.run() # C'est une fonction bloquante du SDK
        except Exception as e:
            print(f"❌ Erreur d'exécution HailoApp: {e}")
            self.running = False

    # Arrête proprement l'application Hailo.
    def stop(self):
        if self.current_app:
            try:
                self.current_app.stop() # Demande au SDK de s'arrêter
                print("🛑 Détecteur Hailo arrêté.")
            except Exception as e:
                print(f"⚠️ Erreur lors de l'arrêt de HailoApp: {e}")
            
            self.running = False
            # On attend que le thread se termine bien
            if self.detection_thread and self.detection_thread.is_alive():
                self.detection_thread.join(timeout=1)
    
    # ---LOGIQUE DE DÉTECTION ET DE DÉCISION ---
    
    def app_callback(self, pad, info, user_data):
        
        # Optimisation : on n'analyse pas toutes les frames si configuré
        user_data.increment()
        if user_data.get_count() % self.config.hailo.frame_skip != 0:
            return Gst.PadProbeReturn.OK
        
        # Extraction des détections depuis le buffer GStreamer
        buffer = info.get_buffer()
        if buffer is None: return Gst.PadProbeReturn.OK
        roi = hailo.get_roi_from_buffer(buffer)
        detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
        
        # On verrouille l'accès aux variables partagées avant de les modifier
        with self.detection_lock:
            # On réinitialise les listes de détection pour cette nouvelle frame
            self.person_centers = []
            self.ball_center = None
            
            # On parcourt tous les objets détectés par l'IA
            for detection in detections:
                label, _, _, _, cx_norm, cy_norm = self._extract_detection_info_norm(detection)
                
                # Les coordonnées sont normalisées [0,1], on les convertit en pixels (ex: 640x640)
                cx = int(cx_norm * self.HEF_WIDTH)
                cy = int(cy_norm * self.HEF_HEIGHT)
                
                # On remplit nos listes avec les objets qui nous intéressent
                if label == "person":
                    self.person_centers.append((cx, cy))
                elif label == "sports ball":
                    self.ball_center = (cx, cy)
            
            # Une fois tous les objets listés, on applique notre logique de priorité
            self._calculate_target_center()

        return Gst.PadProbeReturn.OK

    # Fonction utilitaire pour extraire les informations d'une détection.
    def _extract_detection_info_norm(self, detection):
        label = detection.get_label()
        bbox = detection.get_bbox()
        confidence = detection.get_confidence()
        # Coordonnées du centre de la boîte, normalisées entre 0 et 1
        cx_norm = (bbox.xmin() + bbox.xmax()) / 2
        cy_norm = (bbox.ymin() + bbox.ymax()) / 2
        return label, bbox, confidence, 0, cx_norm, cy_norm

    # Fonction qui trouve la personne la plus proche du ballon.
    def _find_closest_person(self):
        if not self.ball_center: return None
        bx, by = self.ball_center
        min_dist, closest_person = float('inf'), None
        for px, py in self.person_centers:
            dist = math.sqrt((px - bx)**2 + (py - by)**2)
            # On ne considère la personne que si elle est très proche du ballon (ici, moins de 100 pixels)
            if dist < 100 and dist < min_dist:
                min_dist, closest_person = dist, (px, py)
        return closest_person
    
    # L'algorithme de décision : applique la logique de priorité pour choisir la cible finale.
    def _calculate_target_center(self):
        closest = self._find_closest_person()
        
        # Priorité 1 : Suivre le joueur le plus proche du ballon
        if closest:
            self.target_center = closest
            self.mode_text = "Suivi joueur avec ballon"
        # Priorité 2 : S'il n'y a pas de joueur proche, suivre le ballon seul
        elif self.ball_center:
            self.target_center = self.ball_center
            self.mode_text = "Suivi ballon seul"
        # Priorité 3 : S'il n'y a pas de ballon, suivre le centre du groupe de joueurs
        elif self.person_centers:
            # Calcul du Centre de gravité(moyenne des positions)
            self.target_center = (
                sum(x for x, y in self.person_centers) // len(self.person_centers),
                sum(y for x, y in self.person_centers) // len(self.person_centers)
            )
            self.mode_text = "Suivi moyenne des joueurs"
        # Priorité 4 : S'il n'y a rien, la cible est le centre de l'image
        else:
            self.target_center = (self.HEF_WIDTH // 2, self.HEF_HEIGHT // 2)
            self.mode_text = "Pas de détection"
    
    # --- 3.4. INTERFACE PUBLIQUE ---

    # porte d'entrée pour main.py
    # Elle retourne un "rapport de situation" complet et protégé par le verrou.
    def get_detection_status(self):
        with self.detection_lock:
            return {
                'person_count': len(self.person_centers),
                'ball_detected': self.ball_center is not None,
                'mode': self.mode_text,
                'target_center': self.target_center,
                'hef_resolution': (self.HEF_WIDTH, self.HEF_HEIGHT)
            }