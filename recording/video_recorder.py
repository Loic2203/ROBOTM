import time
import cv2  
import os   
import threading  
from datetime import datetime  # Pour générer des noms de fichiers uniques avec la date et l'heure
import numpy as np 

# --- DÉFINITION DE LA CLASSE PRINCIPALE ---
# Cette classe est le "régisseur média". Elle gère tout ce qui est lié à la vidéo de sortie.
class VideoRecorder:
    # ---MÉTHODE __init__ (Le Plan de Construction) ---
    def __init__(self, config):
        self.cfg = config  
        self.streaming_active = True  # Drapeau pour contrôler la boucle de streaming (pas utilisé dans la version actuelle)

        # Drapeaux qui définissent l'état actuel de l'enregistrement
        self.recording = False # Est-ce qu'on est en train d'enregistrer ?
        self.paused = False    # Si on enregistre, est-ce en pause ?
        
        self.writer = None     # L'objet OpenCV VideoWriter qui écrit le fichier vidéo. Initialisé à None.
        self.current_frame = None # La toute dernière image reçue, utilisée pour le streaming web.
        
        # Verrou pour protéger l'accès à `current_frame` depuis plusieurs threads en même temps.
        self.frame_lock = threading.Lock()
        # Verrou pour protéger l'objet `writer`, afin d'éviter les crashs ("race condition").
        self.writer_lock = threading.Lock()

        # --- Buffer pour la fonctionnalité "Clip" (Replay) ---
        self.buffer_size = 200 # Taille du buffer en nombre d'images (ex: 200 images = 10s @ 20fps)
        self.buffer = [None] * self.buffer_size # Crée une liste de taille fixe, remplie de "None"
        self.buffer_idx = 0    # L'index qui indique où écrire la prochaine image dans le buffer
        self.buffer_lock = threading.Lock() # Verrou pour protéger l'accès au buffer

        # Drapeau pour savoir si une création de clip est déjà en cours
        self.clip_running = False

    # ---MÉTHODES DE GESTION DU FLUX ---

    # S'assure que le dossier d'enregistrement existe au démarrage.
    def initialize(self):
        # Crée le dossier spécifié dans la config s'il n'existe pas. 
        os.makedirs(self.cfg.recording.output_dir, exist_ok=True)

    # C'est la fonction la plus importante. Le `main.py` l'appelle à chaque nouvelle image.
    def update_frame(self, frame):
        # Vérification de sécurité : si l'image est invalide, on ne fait rien.
        if frame is None or frame.size == 0:
            return

        # On crée une copie de l'image pour éviter les problèmes de modification par référence entre les threads.
        frame_copy = frame.copy()

        # On met à jour l'image pour le streaming web, en protégeant l'accès avec le verrou.
        with self.frame_lock:
            self.current_frame = frame_copy 

        # On ajoute la nouvelle image au buffer circulaire pour la fonction "Clip".
        with self.buffer_lock:
            self.buffer[self.buffer_idx] = frame_copy
            # On avance l'index, et s'il arrive à la fin, il revient à zéro (comportement circulaire).
            self.buffer_idx = (self.buffer_idx + 1) % self.buffer_size

        # On écrit l'image dans le fichier vidéo SEULEMENT si l'enregistrement est actif et non en pause.
        with self.writer_lock: # On verrouille l'accès au writer
            if self.recording and not self.paused and self.writer is not None:
                try:
                    # Écrit l'image dans le fichier MP4.
                    self.writer.write(frame_copy)
                except Exception as e:
                    print(f"Erreur d'écriture vidéo: {e}")

    # Fournit une image compressée en JPEG pour le serveur web.
    def get_frame_jpeg(self):
        # On verrouille l'accès à `current_frame` pour la lire en toute sécurité.
        with self.frame_lock:
            if self.current_frame is not None:
                # On compresse l'image en JPEG avec la qualité définie dans la config.
                ret, buf = cv2.imencode('.jpg', self.current_frame,
                                       [cv2.IMWRITE_JPEG_QUALITY, self.cfg.web.jpeg_quality])
                if ret:
                    # On retourne les données brutes du JPEG.
                    return buf.tobytes()
        # Si aucune image n'est disponible, on ne retourne rien.
        return None

    # Retourne l'état actuel de l'enregistrement pour l'interface web.
    def get_record_status(self):
        # Utilise une expression conditionnelle pour déterminer l'état textuel.
        state = "recording" if self.recording and not self.paused \
                else "paused" if self.recording and self.paused \
                else "stopped"
        # Retourne un dictionnaire, facile à convertir en JSON.
        return {"state": state}
    
    # ---FONCTIONS DE CONTRÔLE DE L'ENREGISTREMENT ---

    # Fonction privée qui crée et ouvre le fichier vidéo.
    def _open_writer(self):
        # Génère un nom de fichier unique basé sur la date et l'heure actuelles.
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.cfg.recording.output_dir, 
                            f"recording_{ts}{self.cfg.recording.file_extension}")
        
        # Récupère la taille de l'image pour configurer le fichier vidéo.
        with self.frame_lock:
            if self.current_frame is not None:
                height, width, _ = self.current_frame.shape
                frame_size = (width, height)
            else:
                # Si aucune image n'est encore arrivée, on utilise la taille par défaut de la config.
                frame_size = self.cfg.recording.resolution 

        # Crée l'objet VideoWriter d'OpenCV avec tous les paramètres de la config (codec, fps, taille).
        self.writer = cv2.VideoWriter(path, 
                                      cv2.VideoWriter_fourcc(*self.cfg.recording.codec), 
                                      self.cfg.recording.fps, 
                                      frame_size)
        
        # Vérifie si la création du fichier a réussi.
        if self.writer.isOpened():
             print(f"✅ Enregistrement démarré: {path} (Codec: {self.cfg.recording.codec})")
        else:
             print(f"❌ Erreur: Impossible d'ouvrir VideoWriter pour {path}. Codec/Extension incorrect.")
             self.writer = None # S'assure que le writer est None en cas d'échec.

    # Démarre une nouvelle session d'enregistrement.
    def start_recording(self):
        with self.writer_lock: # Verrouille pour éviter les conflits
            if self.recording: return # Si déjà en cours, ne rien faire
            self._open_writer()
            if self.writer is not None: # Ne démarre que si le fichier est bien ouvert
                self.recording = True
                self.paused = False

    # Met en pause l'enregistrement en cours.
    def pause_recording(self):
        with self.writer_lock:
            if self.recording and not self.paused:
                self.paused = True
                print("Enregistrement mis en PAUSE.")

    # Reprend un enregistrement mis en pause.
    def resume_recording(self):
        with self.writer_lock:
            if self.recording and self.paused:
                self.paused = False
                print("Enregistrement repris.")

    # Arrête l'enregistrement et finalise le fichier.
    def stop_recording(self):
        with self.writer_lock: # Verrouille pour arrêter en toute sécurité
            if not self.recording: return
            self.recording = False
            self.paused = False
            if self.writer:
                # C'est l'étape la plus importante : `release()` finalise le fichier et le rend lisible.
                self.writer.release()
                self.writer = None # Réinitialise le writer
                print("Enregistrement STOPPÉ et fichier fermé.")
    
    # Nettoie les ressources à l'arrêt du programme principal.
    def cleanup(self):
        self.stop_recording()

    # --- 2.4. FONCTIONS D'ARCHIVAGE (MINIATURES, ETC.) ---

    # Crée une miniature pour une vidéo déjà enregistrée.
    def generate_thumbnail(self, video_path, thumb_path):
        if os.path.exists(thumb_path): return True # Si la miniature existe déjà, ne rien faire
        
        cap = cv2.VideoCapture(video_path) # Ouvre le fichier vidéo
        if not cap.isOpened(): return False

        # Avance de quelques frames pour éviter les premières images qui sont parfois noires.
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(10, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) - 1)))
        
        ret, frame = cap.read() # Lit une seule image
        cap.release() # Ferme le fichier vidéo

        if ret and frame is not None:
            # Redimensionne l'image et la sauvegarde en tant que JPEG.
            thumb = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
            cv2.imwrite(thumb_path, thumb, [cv2.IMWRITE_JPEG_QUALITY, self.cfg.web.jpeg_quality])
            print(f"Miniature créée: {thumb_path}")
            return True
        return False

    # Extrait une image spécifique d'une vidéo.
    def get_video_frame(self, video_path, frame_index):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened(): return None, "Vidéo non trouvée"

        # Positionne la tête de lecture à l'image demandée.
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        
        ret, frame = cap.read() # Lit l'image
        cap.release()

        if ret and frame is not None:
            # Compresse l'image en JPEG et la retourne.
            ret_enc, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ret_enc: return buf.tobytes(), None
            return None, "Échec de l'encodage JPEG"
        return None, f"Frame {frame_index} non trouvée"
        
    # ---FONCTIONS "CLIP" (REPLAY) ---

    # Fonction publique appelée par l'API pour démarrer la création d'un clip.
    def capture_clip(self):
        if self.clip_running: return False # Empêche de lancer plusieurs créations en même temps
        self.clip_running = True
        # Lance le travail lourd dans un thread séparé pour ne pas bloquer le système.
        threading.Thread(target=self._real_clip_worker, daemon=True).start()
        return True

    # Le "worker" qui crée le clip en arrière-plan.
    def _real_clip_worker(self):
        try:
            print("Clip lancé — préparation...")
            time.sleep(0.1)  

            # On copie le contenu actuel du buffer (le passé).
            with self.buffer_lock:
                saved_buffer = [f.copy() for f in self.buffer if f is not None]

            # On capture quelques images en direct (le futur).
            live_frames = []
            for _ in range(40): # Ex: 40 frames = 2s @ 20fps
                with self.frame_lock:
                    if self.current_frame is not None:
                        live_frames.append(self.current_frame.copy())
                time.sleep(1.0 / self.cfg.recording.fps)  

            # On assemble le passé récent et le futur proche pour créer le clip final.
            all_frames = saved_buffer[-160:] + live_frames # Ex: 160 frames (8s) + 40 frames (2s) = 10s

            if len(all_frames) < 30: # Vérification de sécurité
                print("Pas assez de frames pour le clip")
                self.clip_running = False
                return

            # On crée un nouveau fichier vidéo pour le clip.
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self.cfg.recording.output_dir, f"clip_{ts}{self.cfg.recording.file_extension}")
            h, w, _ = all_frames[0].shape 
            out = cv2.VideoWriter(path, 
                                  cv2.VideoWriter_fourcc(*self.cfg.recording.codec), 
                                  self.cfg.recording.fps, 
                                  (w, h)) 
            
            # On écrit toutes les images dans le fichier clip et on le ferme.
            if out.isOpened():
                for f in all_frames:
                    out.write(f)
                out.release()
                print(f"✅ CLIP SAUVEGARDÉ → {path}")
            else:
                 print(f"❌ Erreur: Impossible d'ouvrir VideoWriter pour CLIP.")

        except Exception as e:
            print(f"Erreur clip : {e}")
        finally:
            # Quoi qu'il arrive (succès ou erreur), on réinitialise le drapeau.
            self.clip_running = False
            print("Clip terminé — flux intact")