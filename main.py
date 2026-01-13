"""  
Système de diffusion Hailo CSI TV-Like avec deux caméras  
(Détection Hailo en Background sur Caméra 0, Suivi/Diffusion sur Caméra 1)
"""  
import threading                      
import signal                         # Pour gérer l'arrêt propre du programme (ex: Ctrl+C)
import time                           # Pour la gestion du temps (pauses, timestamps)
import atexit                         # Pour s'assurer que la fonction stop() est appelée à la fin
import cv2                            
import numpy as np                    
import gi                             # Pour l'intégration avec les bibliothèques GObject (nécessaire pour GStreamer)
import traceback                      # Pour afficher des informations détaillées en cas d'erreur
gi.require_version('Gst', '1.0')      # Spécifie la version de GStreamer à utiliser
from gi.repository import Gst, GLib   # Importe les composants principaux de GStreamer et sa boucle d'événements
from adafruit_servokit import ServoKit  
from picamera2 import Picamera2       
 
# Importations de nos propres modules.
from config.settings import Config          
from web.app import WebServer               
from recording.video_recorder import VideoRecorder 
from detector import HailoDetector        
  
# ---DÉFINITION DE LA CLASSE PRINCIPALE ---
class HailoCSISystem:  
    # Le constructeur est appelé une seule fois au démarrage pour initialiser l'état du système.
    def __init__(self):  
        # Création des instances de nos services principaux
        self.config = Config() 
        self.video_recorder = VideoRecorder(self.config)  
        self.detector = HailoDetector(self.config)  
        self.web_server = None  # Le serveur web sera créé plus tard, dans initialize()
        
        # Variable d'état pour savoir si le programme doit continuer à tourner
        self.running = False  
        
        # Variables pour la gestion de la caméra de diffusion (Caméra 1)
        self.ptz_camera = None             # L'objet Picamera2 Elle permet d'accéder aux réglages physiques (exposition, focus, résolution).
        self.ptz_camera_running = False    # Démarrer et arrêter proprement le thread
        self.ptz_stream_thread = None      # Le thread qui capture les images Cela évite que l'IA ne ralentisse la vidéo.
        self.ptz_pipeline = None           # Le pipeline GStreamer pour le traitement de la vidéo
        self.ptz_loop = None               # C'est le moteur interne de GStreamer qui surveille que le flux vidéo tourne bien sans erreur.
        self.ptz_frame = None              # La dernière image traitée, prête pour la diffusion
        self.ptz_frame_lock = threading.Lock()  # Verrou pour protéger l'accès à self.ptz_frame

        # Variables pour l'optimisation CPU (délestage)
        self.last_proc_time = 0.0          # l'heure exacte à laquelle l'IA a fini d'analyser la dernière image.
        self.processing_fps = 20.0         # Cible de FPS pour le traitement 
          
        # Variables pour le contrôle des servos
        self.kit = ServoKit(channels=16)   
        self.current_pan_angle = 90        
        self.current_tilt_angle = self.config.servo.fixed_tilt_angle # Position verticale fixe
        self.current_zoom = 1.0            # Zoom numérique de départ

        # ===================================================================================
        # VARIABLES D'ÉTAT POUR LA LOGIQUE DE SUIVI DE MOUVEMENT 
        # ===================================================================================
        hef_center = (self.detector.HEF_WIDTH // 2, self.detector.HEF_HEIGHT // 2) # Coordonnées du centre de l'image de l'IA
        self.smoothed_target_center = hef_center  # Position de la "cible virtuelle" lissée, initialisée au centre
        self.last_detection_time = 0.0      # Chronomètre de la dernière fois qu'une cible a été vue
        self.is_target_lost = True          # Drapeau : est-ce que la cible est considérée comme perdue ? (Oui au début)
        self.is_returning_to_center = False # Drapeau : est-ce qu'on est en train de balayer vers le centre ? (Non au début)
        self.last_error_sign = 0            # Mémoire du signe de l'erreur pour la correction de dépassement
        # ===================================================================================
        
        Gst.init(None) # Initialisation globale de GStreamer
      
    # Met en place et démarre tous les composants dans le bon ordre.
    def initialize(self):  
        print("🚀 Initialisation du système Hailo CSI TV-Like...")  
        
        # On démarre le cerveau IA en premier
        self.detector.start()
        
        try:
            # Démarrage de la caméra de diffusion (Caméra 1)
            print("📷 Initialisation manuelle de la caméra PTZ (Caméra 1)...")
            self.ptz_camera = Picamera2(camera_num=1) 
            WIDTH, HEIGHT = self.config.recording.resolution
            config = self.ptz_camera.create_video_configuration(main={"size": (WIDTH, HEIGHT), "format": "RGB888"})
            self.ptz_camera.configure(config)
            self.ptz_camera.start() 
            self.ptz_camera_running = True
            time.sleep(1) # Laisse le temps à la caméra de se stabiliser
            print("✅ Caméra PTZ stabilisée.")
            
            # Création du pipeline GStreamer qui va recevoir les images de cette caméra
            if not self._create_ptz_pipeline(): return False
            
            # Lancement du thread qui va faire le pont entre Picamera2 et GStreamer
            self.ptz_stream_thread = threading.Thread(target=self._run_ptz_stream, daemon=True)
            self.ptz_stream_thread.start()
            
        except Exception as e:
            print(f"❌ Erreur critique lors de l'initialisation de la caméra PTZ (Caméra 1): {e}")
            traceback.print_exc()
            self.detector.stop() # On arrête le détecteur si la caméra échoue
            return False

        # Démarrage des autres services
        self.video_recorder.initialize()  # Prépare le gestionnaire média
        self.web_server = WebServer(self.video_recorder, self.config, self)  # Crée et démarre le serveur web
        self.web_server.start()  
        
        # Positionnement initial des servos
        self.kit.servo[self.config.servo.pan_channel].angle = self.current_pan_angle
        self.kit.servo[self.config.servo.tilt_channel].angle = self.current_tilt_angle
        
        print("✅ Système initialisé - Deux caméras actives (Détection en Background)")  
        return True  
      
    # ---MÉTHODES DE GESTION DU FLUX VIDÉO ---
    
    # Construit le pipeline GStreamer pour la caméra de diffusion.
    def _create_ptz_pipeline(self):  
        try:  
            WIDTH, HEIGHT = self.config.recording.resolution
            # 'appsrc' est l'entrée : notre code Python va "pousser" des images ici.
            # 'appsink' est la sortie : notre code Python va "tirer" des images d'ici pour les traiter.
            pipeline_str = f"appsrc name=ptz_source is-live=true format=GST_FORMAT_TIME block=true ! video/x-raw,format=RGB,width={WIDTH},height={HEIGHT},framerate=30/1 ! videoconvert ! video/x-raw,format=BGR ! appsink name=ptz_sink emit-signals=true sync=false"  
            self.ptz_pipeline = Gst.parse_launch(pipeline_str)  
            
            # On connecte notre fonction _on_ptz_sample au signal "new-sample" de l'appsink.
            # C'est ce qui fait que notre logique s'exécute à chaque nouvelle image.
            appsink = self.ptz_pipeline.get_by_name("ptz_sink")  
            appsink.connect("new-sample", self._on_ptz_sample)  
            
            self.ptz_pipeline.set_state(Gst.State.PLAYING) # On lance le pipeline
            print("✅ Pipeline de diffusion créé")  
            return True  
        except Exception as e:  
            print(f"❌ Erreur pipeline de diffusion: {e}")  
            traceback.print_exc()
            return False  
    
    # Fonction exécutée dans un thread dédié pour alimenter le pipeline GStreamer.
    def _run_ptz_stream(self):
        print("Processus Picamera2 démarré")
        appsrc = self.ptz_pipeline.get_by_name("ptz_source")
        try:
            self.ptz_camera.capture_array("main") # Fait une première capture "à blanc" pour stabiliser
            print("✅ Capture initiale Picamera2 réussie (Warmup).")
        except Exception as e:
            if self.running: print(f"❌ Erreur CRITIQUE Picamera2 (Warmup): {e}")
            self.ptz_camera_running = False
            if appsrc: appsrc.emit("end-of-stream")
            print("🛑 Thread de stream PTZ arrêté (échec du warmup).")
            return

        # Boucle principale du thread : capturer une image et la pousser dans appsrc.
        while self.running and self.ptz_camera_running:
            try:
                frame_array = self.ptz_camera.capture_array("main")
                if frame_array is None: continue
                buffer = Gst.Buffer.new_wrapped(frame_array.tobytes())
                appsrc.emit("push-buffer", buffer)
                time.sleep(1.0 / self.config.recording.fps) # Attend un peu pour viser le bon FPS
            except Exception as e:
                if self.running: print(f"❌ Erreur CRITIQUE dans le thread de stream PTZ (Boucle): {e}") 
                break
        
        if appsrc: appsrc.emit("end-of-stream") # Signal de fin de flux
        self.ptz_camera_running = False
        print("🛑 Thread de stream PTZ arrêté.")

    # ---MÉTHODE _on_ptz_sample---
    # Cette fonction est le "cerveau actif" du système. Elle s'exécute à chaque nouvelle image.
    def _on_ptz_sample(self, sink):  
        # Étape 0 : Récupération de la nouvelle image depuis GStreamer
        sample = sink.emit("pull-sample")  
        if not sample: return Gst.FlowReturn.OK
        buffer = sample.get_buffer()  
        caps = sample.get_caps()  
        height = caps.get_structure(0).get_value("height")  
        width = caps.get_structure(0).get_value("width")  
        success, map_info = buffer.map(Gst.MapFlags.READ)  
        if not success: return Gst.FlowReturn.OK
        
        try:
            # Étape 1 : PERCEPTION - Interroger le cerveau IA
            detection_status = self.detector.get_detection_status()
            hef_w, hef_h = detection_status['hef_resolution']
            current_time = time.time()

            # Étape 2 : DÉCISION (Partie 1) - Gestion de la Cible (Détection / Perte / Recherche)
            target_detected = detection_status['person_count'] > 0 or detection_status['ball_detected']

            if target_detected: # Cas 1 : On voit la cible
                self.last_detection_time = current_time
                self.is_target_lost = False
                self.is_returning_to_center = False
                current_target_center = detection_status['target_center']
            else: # Cas 2 : On ne voit plus la cible
                self.is_target_lost = True
                time_since_lost = current_time - self.last_detection_time
                
                if time_since_lost < self.config.servo.target_lost_wait_duration: # Phase d'attente
                    current_target_center = self.smoothed_target_center
                else: # Phase de recherche
                    self.is_returning_to_center = True
                    current_target_center = (hef_w // 2, hef_h // 2)

            # Étape 3 : DÉCISION (Partie 2) - Lissage et Calcul de la Vitesse
            # Lissage de la cible pour l'inertie
            sx, sy = self.smoothed_target_center  #position actuelle de la caméra
            tx, ty = current_target_center        #position cible
            alpha = self.config.servo.return_to_center_speed if self.is_returning_to_center else self.config.servo.target_smoothing_factor
            sx += alpha * (tx - sx); sy += alpha * (ty - sy) #Au lieu de sauter directement de sx à tx, on dit au robot : "Avance seulement d'un petit pourcentage (alpha) de la distance qui te sépare de la cible"
            self.smoothed_target_center = (sx, sy) #On enregistre cette nouvelle position intermédiaire pour le prochain calcul.
            
            # Calcul de l'erreur de position(Il sert à mesurer la distance entre la cible et le centre de l'image)
            center_error_x_hef = self.smoothed_target_center[0] - hef_w / 2 #On calcule la distance (en pixels) entre le centre de la cible (lissée) et le centre exact du flux vidéo (hef_w / 2).
            error_abs = abs(center_error_x_hef)
            
            # Détection du dépassement
            current_error_sign = 1 if center_error_x_hef > 0 else -1 if center_error_x_hef < 0 else 0  # Détection du signe de l'erreur
            has_overshot = (self.last_error_sign != 0 and current_error_sign != 0 and self.last_error_sign != current_error_sign)
            self.last_error_sign = current_error_sign #On mémorise la direction actuelle pour pouvoir faire la comparaison lors de la prochaine image
            
            # Modulation de la vitesse (logique lent/vite/lent)
            slow_thresh = self.config.servo.slow_move_threshold_pixels
            slow_smooth = self.config.servo.slow_smoothing_factor
            fast_smooth = self.config.servo.fast_smoothing_factor
            if has_overshot: #Si le robot vient de dépasser sa cible, il passe immédiatement en slow_smooth (vitesse lente).
                dynamic_smoothing = slow_smooth # Correction douce après dépassement
            elif error_abs < slow_thresh:  #Si la cible est déjà proche du centre (l'erreur est petite), on utilise aussi la vitesse lente
                dynamic_smoothing = slow_smooth # Mouvement court et lent
            else:   #la cible s'échappe rapidement vers le bord de l'écran
                progress = min(1.0, (error_abs - slow_thresh) / (hef_w / 2 - slow_thresh)) #On calcule à quel point la cible est loin du centre (entre 0.0 et 1.0)
                dynamic_smoothing = slow_smooth + progress * (fast_smooth - slow_smooth) # Mouvement long avec accélération
            
            # Étape 4 : ACTION - Commande du Servo
            # Conversion de l'erreur en angle, avec application de l'offset de calibration
            raw_target_angle = 90 + (center_error_x_hef / (hef_w / 2)) * (self.config.servo.max_angle - 90) #Conversion Pixels → Degrés 
            if raw_target_angle > 90: #Correction mécanique
                corrected_target_angle = raw_target_angle + self.config.servo.pan_offset_right
            elif raw_target_angle < 90:
                corrected_target_angle = raw_target_angle + self.config.servo.pan_offset_left
            else:
                corrected_target_angle = 90.0
            
            # Application de la vitesse dynamique pour un mouvement fluide vers l'angle cible
            target_angle = corrected_target_angle
            new_pan_angle = self.current_pan_angle + dynamic_smoothing * (target_angle - self.current_pan_angle) #C'est la ligne la plus importante. Au lieu de dire au moteur : "Saute directement à l'objectif",On calcule la distance qui reste à parcourir (l'écart).
            new_pan_angle = max(self.config.servo.min_angle, min(self.config.servo.max_angle, new_pan_angle)) #On s'assure que l'angle calculé ne dépasse jamais les limites physiques du robot
            
            # Envoi de la commande au moteur
            if abs(self.current_pan_angle - new_pan_angle) > 0.1:#Avant d'envoyer l'ordre au moteur, Si le mouvement est plus petit que 0,1°, on ne fait rien.
                self.kit.servo[self.config.servo.pan_channel].angle = int(new_pan_angle)
                self.current_pan_angle = new_pan_angle
            
            # Étape 5 : DIFFUSION - Préparation de l'Image Finale
            # Calcul du zoom numérique 
            desired_zoom = 1.0 + (error_abs / (hef_w / 2)) * (self.config.zoom.max_zoom - 1.0)
            self.current_zoom = min(self.config.zoom.max_zoom, max(self.config.zoom.min_zoom, desired_zoom))

            # Conversion des coordonnées pour le traitement d'image
            target_cx_ptz = (self.smoothed_target_center[0] / hef_w) * width
            target_cy_ptz = (self.smoothed_target_center[1] / hef_h) * height

            # Logique de délestage CPU : on ne fait le traitement lourd qu'à 20 FPS
            if (current_time - self.last_proc_time) >= (1.0 / self.processing_fps):
                raw_frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((height, width, 3))
                raw_frame = cv2.cvtColor(raw_frame, cv2.COLOR_RGB2BGR)
                zoomed_frame = self._apply_zoom_crop(raw_frame, self.current_zoom, target_cx_ptz, target_cy_ptz)  
                final_frame = self._add_frame_info(zoomed_frame)  
                
                # On met à jour l'image finale et on l'envoie au gestionnaire média
                with self.ptz_frame_lock:
                    self.ptz_frame = final_frame
                self.video_recorder.update_frame(final_frame)  
                
                self.last_proc_time = current_time

        except Exception as e:
            print(f"❌ Erreur lors du traitement du frame PTZ (Callback): {e}")
            traceback.print_exc()
        finally:
            # Très important : on libère la mémoire de l'image GStreamer
            buffer.unmap(map_info)  
        return Gst.FlowReturn.OK  
      
    # --- MÉTHODES UTILITAIRES ---

    # Applique un zoom numérique en recadrant l'image.
    def _apply_zoom_crop(self, frame, zoom, target_cx, target_cy):  
        height, width = frame.shape[:2]  
        crop_w, crop_h = int(width / zoom), int(height / zoom)  
        start_x = max(0, min(width - crop_w, int(target_cx - crop_w / 2)))  
        start_y = max(0, min(height - crop_h, int(target_cy - crop_h / 2)))  
        cropped = frame[int(start_y):int(start_y + crop_h), int(start_x):int(start_x + crop_w)]  
        return cv2.resize(cropped, (width, height), interpolation=cv2.INTER_LINEAR)  
      
    # Ajoute les informations de statut (texte) sur l'image.
    def _add_frame_info(self, frame):  
        frame_with_info = frame.copy()  
        height, width = frame.shape[:2]  
        status = self.detector.get_detection_status()
        cv2.putText(frame_with_info, f"{width}x{height} | HAILO TV", (10, height - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)  
        cv2.putText(frame_with_info, f"{time.strftime('%H:%M:%S')}", (10, height - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)  
        cv2.putText(frame_with_info, f"Mode: {status['mode']}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)  
        cv2.putText(frame_with_info, f"Zoom: {self.current_zoom:.1f}x", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)  
        cv2.putText(frame_with_info, f"Pan Angle: {int(self.current_pan_angle)}°", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)  
        return frame_with_info  
      
    # --- MÉTHODES DE CYCLE DE VIE ---
    
    # Démarre l'application.
    def start(self):  
        if not self.initialize(): return False  # S'assure que tout est bien initialisé
        self.running = True  
        self.ptz_loop = GLib.MainLoop()  # Lance la boucle d'événements GStreamer
        threading.Thread(target=self.ptz_loop.run, daemon=True).start()  
        print(f"✅ Systèmes démarrés - Interface: {self.config.get_server_url()}")  
        while self.running: time.sleep(1) # Boucle principale qui maintient le programme en vie
      
    # Arrête proprement tous les composants.
    def stop(self):  
        print("\n🛑 Arrêt...")  
        self.running = False  
        
        # On arrête tout dans l'ordre inverse du démarrage pour éviter les erreurs
        self.ptz_camera_running = False
        if self.ptz_stream_thread and self.ptz_stream_thread.is_alive():
            self.ptz_stream_thread.join(timeout=2)
        if self.ptz_camera:
             try: self.ptz_camera.close() 
             except: pass
        self.detector.stop() 
        if self.ptz_loop: self.ptz_loop.quit()  
        if self.ptz_pipeline: self.ptz_pipeline.set_state(Gst.State.NULL)  
        if self.web_server: self.web_server.stop()  
        self.video_recorder.cleanup() # S'assure que les fichiers vidéo sont bien fermés
        print("✅ Arrêté")  
  
# --- 3. POINT D'ENTRÉE DU PROGRAMME ---

# Gère l'arrêt propre avec Ctrl+C
def signal_handler(sig, frame):  
    global system
    if system: system.stop()  
  
if __name__ == "__main__":  
    system = None
    try:
        system = HailoCSISystem() # Crée notre objet principal
        # Configure la gestion des signaux d'arrêt
        signal.signal(signal.SIGINT, signal_handler)  
        signal.signal(signal.SIGTERM, signal_handler)  
        atexit.register(lambda: system.stop() if system and system.running else None)  
        
        system.start() # Lance le système
    except Exception as e:
        print(f"❌ Erreur critique non gérée dans __main__: {e}")
        traceback.print_exc()
        if system and system.running:
            system.stop()