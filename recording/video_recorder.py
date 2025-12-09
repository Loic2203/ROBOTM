import time
import cv2
import os
import threading
from datetime import datetime
import numpy as np

class VideoRecorder:
    def __init__(self, config):
        self.cfg = config
        self.streaming_active = True

        self.recording = False
        self.paused = False
        self.writer = None
        self.current_frame = None
        self.frame_lock = threading.Lock()

        # Buffer pour la fonction Clip
        self.buffer_size = 180
        self.buffer = [None] * self.buffer_size
        self.buffer_idx = 0
        self.buffer_lock = threading.Lock()

        self.clip_running = False

    def initialize(self):
        os.makedirs(self.cfg.recording.output_dir, exist_ok=True)

    def update_frame(self, frame):
        if frame is None or frame.size == 0:
            return

        # Assurer que l'on travaille sur une copie avant de la stocker
        frame_copy = frame.copy()

        with self.frame_lock:
            self.current_frame = frame_copy 

        with self.buffer_lock:
            self.buffer[self.buffer_idx] = frame_copy
            self.buffer_idx = (self.buffer_idx + 1) % self.buffer_size

        if self.recording and not self.paused:
            if self.writer:
                try:
                    self.writer.write(frame_copy)
                except Exception as e:
                    print(f"Erreur d'écriture vidéo: {e}")

    def get_frame_jpeg(self):
        with self.frame_lock:
            if self.current_frame is not None:
                ret, buf = cv2.imencode('.jpg', self.current_frame,
                                       [cv2.IMWRITE_JPEG_QUALITY, self.cfg.web.jpeg_quality])
                if ret:
                    return buf.tobytes()
        return None

    def get_record_status(self):
        state = "recording" if self.recording and not self.paused \
                else "paused" if self.recording and self.paused \
                else "stopped"
        return {"state": state}
    
    # ===============================================
    # FONCTIONS DE CONTRÔLE 
    # ===============================================

    def _open_writer(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.cfg.recording.output_dir, 
                            f"recording_{ts}{self.cfg.recording.file_extension}")
        
        with self.frame_lock:
            if self.current_frame is not None:
                height, width, _ = self.current_frame.shape
                frame_size = (width, height)
            else:
                # Utilise la résolution de config si pas de frame
                frame_size = self.cfg.recording.resolution 

        self.writer = cv2.VideoWriter(path, 
                                      cv2.VideoWriter_fourcc(*self.cfg.recording.codec), 
                                      self.cfg.recording.fps, 
                                      frame_size)
        
        if self.writer.isOpened():
             print(f"✅ Enregistrement démarré: {path} (Codec: {self.cfg.recording.codec})")
        else:
             print(f"❌ Erreur: Impossible d'ouvrir VideoWriter pour {path}. Codec/Extension incorrect.")


    def start_recording(self):
        if self.recording:
            return
        self.recording = True
        self.paused = False
        self._open_writer()


    def pause_recording(self):
        if self.recording and not self.paused:
            self.paused = True
            print("Enregistrement mis en PAUSE.")


    def resume_recording(self):
        if self.recording and self.paused:
            self.paused = False
            print("Enregistrement repris.")


    def stop_recording(self):
        if self.recording:
            self.recording = False
            self.paused = False
            if self.writer:
                self.writer.release()
                self.writer = None
                print("Enregistrement STOPPÉ et fichier fermé.")
    
    def cleanup(self):
        """Fonction appelée à l'arrêt du système."""
        self.stop_recording()

    # ===============================================
    # FONCTIONS D'ARCHIVAGE (Miniatures & Frame)
    # ===============================================

    def generate_thumbnail(self, video_path, thumb_path):
        """Génère une miniature à partir de la première frame de la vidéo."""
        if os.path.exists(thumb_path):
            return True
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return False

        # Tenter d'avancer légèrement pour éviter les frames d'initialisation noires
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(10, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) - 1)))
        
        ret, frame = cap.read()
        cap.release()

        if ret and frame is not None:
            thumb = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
            # Utilisation de la qualité JPEG de la config Web
            cv2.imwrite(thumb_path, thumb, [cv2.IMWRITE_JPEG_QUALITY, self.cfg.web.jpeg_quality])
            print(f"Miniature créée: {thumb_path}")
            return True
        else:
            return False

    def get_video_frame(self, video_path, frame_index):
        """Extrait une frame spécifique (index) d'une vidéo et la retourne en JPEG."""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None, "Vidéo non trouvée ou impossible à ouvrir"

        frame_pos = int(frame_index)
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
        
        ret, frame = cap.read()
        cap.release()

        if ret and frame is not None:
            ret_enc, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ret_enc:
                return buf.tobytes(), None
            else:
                return None, "Échec de l'encodage JPEG"
        else:
            return None, f"Frame {frame_pos} non trouvée"
        
    # ===============================================
    # FONCTIONS CLIP 
    # ===============================================

    def capture_clip(self):
        if self.clip_running:
            return False
        self.clip_running = True
        threading.Thread(target=self._real_clip_worker, daemon=True).start()
        return True

    def _real_clip_worker(self):
        try:
            print("Clip lancé — préparation...")
            time.sleep(0.1)  

            with self.buffer_lock:
                # Copie de la liste des frames
                saved_buffer = [f.copy() for f in self.buffer if f is not None]

            live_frames = []
            for _ in range(20): 
                with self.frame_lock:
                    if self.current_frame is not None:
                        live_frames.append(self.current_frame.copy())
                time.sleep(0.01)  

            # On s'assure de n'avoir que 160 frames du passé + 20 frames live (6 secondes @ 30 FPS)
            all_frames = saved_buffer[-160:] + live_frames 

            if len(all_frames) < 30:
                print("Pas assez de frames pour le clip")
                return

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self.cfg.recording.output_dir, f"clip_{ts}{self.cfg.recording.file_extension}")
            h, w, _ = all_frames[0].shape 
            
            out = cv2.VideoWriter(path, 
                                  cv2.VideoWriter_fourcc(*self.cfg.recording.codec), 
                                  self.cfg.recording.fps, 
                                  (w, h)) 
            
            if out.isOpened():
                for f in all_frames:
                    out.write(f)
                out.release()
                print(f"✅ CLIP SAUVEGARDÉ EN 2 SECONDES → {path}")
            else:
                 print(f"❌ Erreur: Impossible d'ouvrir VideoWriter pour CLIP.")

        except Exception as e:
            print(f"Erreur clip : {e}")
        finally:
            self.clip_running = False
            print("Clip terminé — flux intact")
