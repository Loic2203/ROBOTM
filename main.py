 
"""  
Système de diffusion Hailo CSI TV-Like avec deux caméras  
(Détection Hailo en Background sur Caméra 0, Suivi/Diffusion sur Caméra 1)
"""  
  
import threading                      
import signal  
import time  
import atexit  
import cv2  
import numpy as np  
import gi  
import traceback 
gi.require_version('Gst', '1.0')  
from gi.repository import Gst, GLib  
from adafruit_servokit import ServoKit  
from picamera2 import Picamera2 
from config.settings import Config  
from web.app import WebServer  
from recording.video_recorder import VideoRecorder  
from detector import HailoDetector  
  
class HailoCSISystem:  
    def __init__(self):  
        self.config = Config()  
        self.video_recorder = VideoRecorder(self.config)  
        self.detector = HailoDetector(self.config)  
        self.web_server = None  
        self.running = False  
        
        # --- ÉLÉMENTS POUR PTZ PICAMERA2/APPSRC ---
        self.ptz_camera = None      
        self.ptz_camera_running = False
        self.ptz_stream_thread = None 
        
        self.ptz_pipeline = None    
        self.ptz_loop = None  
        self.ptz_frame = None       
        self.ptz_frame_lock = threading.Lock()  

        # --- NOUVEAU: Variables pour le délestage CPU ---
        self.last_proc_time = 0.0
        self.processing_fps = 10.0 # Traitement d'image lourd à 10 FPS max
          
        # Servo  
        self.kit = ServoKit(channels=16)  
        self.current_pan_angle = 90  
        self.current_tilt_angle = self.config.servo.fixed_tilt_angle
        self.current_zoom = 1.0  
        
        Gst.init(None)
      
    def initialize(self):  
        """Initialise tous les composants"""  
        print("🚀 Initialisation du système Hailo CSI TV-Like...")  
          
        # 1. Démarrer le Détecteur Hailo (Caméra 0)
        self.detector.start()
        
        # 2. Initialiser la caméra PTZ (Caméra 1) via Picamera2
        try:
            print("📷 Initialisation manuelle de la caméra PTZ (Caméra 1)...")
            self.ptz_camera = Picamera2(camera_num=1) 
            WIDTH, HEIGHT = self.config.recording.resolution
            
            # Configuration en 1920x1080 (haute résolution du settings.py)
            config = self.ptz_camera.create_video_configuration(
                main={"size": (WIDTH, HEIGHT), "format": "RGB888"}
            )
            self.ptz_camera.configure(config)
            self.ptz_camera.start() 
            self.ptz_camera_running = True
            
            time.sleep(1) # Délai de stabilisation
            print("✅ Caméra PTZ stabilisée.")
            
            # 3. Créer le pipeline PTZ GStreamer avec appsrc (source Python)
            if not self._create_ptz_pipeline():  
                self.detector.stop()
                self.ptz_camera.close()
                return False
            
            # 4. Démarrer le thread d'acquisition Picamera2 -> GStreamer (Appsrc)
            self.ptz_stream_thread = threading.Thread(target=self._run_ptz_stream, daemon=True)
            self.ptz_stream_thread.start()
            
        except Exception as e:
            print(f"❌ Erreur critique lors de l'initialisation de la caméra PTZ (Caméra 1): {e}")
            traceback.print_exc()
            self.detector.stop()
            return False

        # 5. Initialiser recorder  
        self.video_recorder.initialize()  
          
        # 6. Démarrer serveur web  
        self.web_server = WebServer(self.video_recorder, self.config, self)  
        self.web_server.start()  
          
        # 7. Initialiser servo
        self.kit.servo[self.config.servo.pan_channel].angle = self.current_pan_angle
        self.kit.servo[self.config.servo.tilt_channel].angle = self.current_tilt_angle

          
        print("✅ Système initialisé - Deux caméras actives (Détection en Background)")  
        return True  
      
    def _create_ptz_pipeline(self):  
        """Pipeline GStreamer pour la haute (diffusion) utilisant appsrc comme source."""
        try:  
            WIDTH, HEIGHT = self.config.recording.resolution
            
            # Appsrc est le point d'entrée du thread Python
            pipeline_str = f"""  
                appsrc name=ptz_source is-live=true format=GST_FORMAT_TIME block=true ! 
                video/x-raw,format=RGB,width={WIDTH},height={HEIGHT},framerate=30/1 !   
                videoconvert !   
                video/x-raw,format=BGR !   
                appsink name=ptz_sink emit-signals=true sync=false  
            """  
            
            self.ptz_pipeline = Gst.parse_launch(pipeline_str)  
            
            appsink = self.ptz_pipeline.get_by_name("ptz_sink")  
            appsink.connect("new-sample", self._on_ptz_sample)  
            
            self.ptz_pipeline.set_state(Gst.State.PLAYING) 
            print("✅ Pipeline haute (diffusion) créé")  
            return True  
        except Exception as e:  
            print(f"❌ Erreur pipeline haute: {e}")  
            traceback.print_exc()
            return False  
    
    def _run_ptz_stream(self):
        """Thread pour l'acquisition des frames de Picamera2 et l'envoi vers appsrc."""
        print("picamera_process started")
        appsrc = self.ptz_pipeline.get_by_name("ptz_source")
        
        try:
            # --- CORRECTION STABILITÉ (WARMUP) ---
            self.ptz_camera.capture_array("main") 
            print("✅ Picamera2 capture initial réussie (Warmup).")
        except Exception as e:
            if self.running:
                print(f"❌ Erreur CRITIQUE Picamera2 (Warmup): {e}")
                traceback.print_exc() 
            self.ptz_camera_running = False
            if appsrc:
                 appsrc.emit("end-of-stream")
            print("🛑 Thread de stream PTZ arrêté (échec du warmup).")
            return

        # Boucle principale
        while self.running and self.ptz_camera_running:
            try:
                frame_array = self.ptz_camera.capture_array("main")
                
                if frame_array is None:
                    time.sleep(0.001)
                    continue
                
                data = frame_array.tobytes()
                buffer = Gst.Buffer.new_wrapped(data)
                
                appsrc.emit("push-buffer", buffer)
                
                time.sleep(1.0 / self.config.recording.fps)

            except Exception as e:
                if self.running:
                    print(f"❌ Erreur CRITIQUE dans le thread de stream PTZ (Boucle): {e}") 
                    traceback.print_exc() 
                break
            
        # Arrêt
        if appsrc:
            appsrc.emit("end-of-stream")
        self.ptz_camera_running = False
        print("🛑 Thread de stream PTZ arrêté.")

    def _on_ptz_sample(self, sink):  
        """Callback GStreamer pour frames de la haute (applique zoom/crop basé sur détection, met à jour recorder, contrôle servo)"""  
        sample = sink.emit("pull-sample")  
        if sample:  
            buffer = sample.get_buffer()  
            caps = sample.get_caps()  
            height = caps.get_structure(0).get_value("height")  
            width = caps.get_structure(0).get_value("width")  
            success, map_info = buffer.map(Gst.MapFlags.READ)  
            if success:  
                try:
                    raw_frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((height, width, 3))  
                    raw_frame = cv2.cvtColor(raw_frame, cv2.COLOR_RGB2BGR)

                    detection_status = self.detector.get_detection_status()
                    target_cx_hef, target_cy_hef = detection_status['target_center']
                    hef_w, hef_h = detection_status['hef_resolution']
                    
                    # --- LOGIQUE SERVO (À 30 FPS pour un suivi fluide) ---
                    center_error_x_hef = target_cx_hef - hef_w // 2 
                    
                    # 1. PAN FLUID
                    error_ratio = center_error_x_hef / (hef_w / 2) 
                    range_angle = self.config.servo.max_angle - self.config.servo.min_angle
                    target_angle = 90 + (error_ratio * (range_angle / 2))
                    
                    smoothing = self.config.servo.smoothing_factor
                    new_pan_angle = self.current_pan_angle + smoothing * (target_angle - self.current_pan_angle) 
                    new_pan_angle = max(self.config.servo.min_angle, min(self.config.servo.max_angle, new_pan_angle))  
                    
                    hysteresis_norm = self.config.servo.hysteresis_pixels / (hef_w / 2)
                    
                    if abs(error_ratio) > hysteresis_norm:
                        self.kit.servo[self.config.servo.pan_channel].angle = int(new_pan_angle)  
                        self.current_pan_angle = new_pan_angle  
                        
                    # 2. ZOOM/CROP Numérique (Calcul seulement, pas l'application coûteuse)
                    center_error_x_abs = abs(center_error_x_hef) 
                    desired_zoom = 1.0 + (center_error_x_abs / (hef_w / 2)) * (self.config.zoom.max_zoom - 1)  
                    self.current_zoom = min(self.config.zoom.max_zoom, max(self.config.zoom.min_zoom, desired_zoom))  
                    
                    target_cx_ptz = (target_cx_hef / hef_w) * width
                    target_cy_ptz = (target_cy_hef / hef_h) * height

                    # --- LOGIQUE D'IMAGE (À 10 FPS pour le délestage CPU) ---
                    current_time = time.time()
                    if (current_time - self.last_proc_time) >= (1.0 / self.processing_fps):
                        
                        # 3. Application du Zoom et du Crop (coûteux)
                        zoomed_frame = self._apply_zoom_crop(raw_frame, self.current_zoom, target_cx_ptz, target_cy_ptz)  
                          
                        # 4. Ajouter infos (coûteux)
                        final_frame = self._add_frame_info(zoomed_frame)  
                          
                        # 5. Mettre à jour recorder et stream (mise à jour)
                        with self.ptz_frame_lock:
                            self.ptz_frame = final_frame
                        self.video_recorder.update_frame(final_frame)  
                        
                        self.last_proc_time = current_time
                    
                    # Si on ne traite pas, le recorder et le stream continuent d'utiliser le dernier self.ptz_frame.

                except Exception as e:
                    print(f"❌ Erreur lors du traitement du frame PTZ (Callback): {e}")
                    traceback.print_exc()
                finally:
                    buffer.unmap(map_info)  
        return Gst.FlowReturn.OK  
      
    def _apply_zoom_crop(self, frame, zoom, target_cx, target_cy):  
        """Applique zoom/crop centré sur cible"""  
        height, width = frame.shape[:2]  
        crop_w, crop_h = int(width / zoom), int(height / zoom)  
          
        start_x = max(0, min(width - crop_w, int(target_cx - crop_w / 2)))  
        start_y = max(0, min(height - crop_h, int(target_cy - crop_h / 2)))  
          
        cropped = frame[int(start_y):int(start_y + crop_h), int(start_x):int(start_x + crop_w)]  
        return cv2.resize(cropped, (width, height), interpolation=cv2.INTER_LINEAR)  
      
    def _add_frame_info(self, frame):  
        """Ajoute infos sur frame"""  
        frame_with_info = frame.copy()  
        height, width = frame.shape[:2]  
        
        status = self.detector.get_detection_status()
        
        # ... (le code d'overlay reste inchangé) ...
        cv2.putText(frame_with_info, f"{width}x{height} | HAILO TV", (10, height - 30),   
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)  
        cv2.putText(frame_with_info, f"{time.strftime('%H:%M:%S')}", (10, height - 10),   
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)  
          
        cv2.putText(frame_with_info, f"Mode: {status['mode']}", (10, 30),   
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)  
        cv2.putText(frame_with_info, f"Zoom: {self.current_zoom:.1f}x", (10, 60),   
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)  
        cv2.putText(frame_with_info, f"Pan Angle: {int(self.current_pan_angle)}°", (10, 90),   
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)  
          
        return frame_with_info  
      
    def start(self):  
        if not self.initialize():  
            return False  
          
        self.running = True  
          
        self.ptz_loop = GLib.MainLoop()  
        ptz_gstreamer_thread = threading.Thread(target=self.ptz_loop.run, daemon=True)  
        ptz_gstreamer_thread.start()  
          
        print(f"✅ Systèmes démarrés - Interface: {self.config.get_server_url()}")  
        while self.running:  
            time.sleep(1) 
      
    def stop(self):  
        print("\n🛑 Arrêt...")  
        self.running = False  
        
        # 1. Arrêt Picamera2 et du thread de stream
        self.ptz_camera_running = False
        if self.ptz_stream_thread and self.ptz_stream_thread.is_alive():
            self.ptz_stream_thread.join(timeout=2)
        if self.ptz_camera:
             try:
                self.ptz_camera.close() 
             except:
                pass

        # 2. Arrêt du détecteur Hailo
        self.detector.stop() 
        
        # 3. Arrêt du pipeline PTZ GStreamer
        if self.ptz_loop:  
            self.ptz_loop.quit()  
        if self.ptz_pipeline:  
            self.ptz_pipeline.set_state(Gst.State.NULL)  
            
        # 4. Arrêt des autres composants
        if self.web_server:  
            self.web_server.stop()  
        self.video_recorder.cleanup()  
        print("✅ Arrêté")  
  
def signal_handler(sig, frame):  
    if 'system' in globals():  
        system.stop()  
  
if __name__ == "__main__":  
    system = None
    try:
        signal.signal(signal.SIGINT, signal_handler)  
        signal.signal(signal.SIGTERM, signal_handler)  
        atexit.register(lambda: system.stop() if 'system' in globals() and system.running else None)  
      
        system = HailoCSISystem()  
        system.start()
    except Exception as e:
        print(f"❌ Erreur critique non gérée: {e}")
        if system and system.running:
            system.stop()
        traceback.print_exc()
