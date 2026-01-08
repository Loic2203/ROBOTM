"""
Pipeline GStreamer pour la gestion du Double Caméra CSI avec Hailo
"""

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstApp', '1.0')
from gi.repository import Gst

class HailoPipeline:
    """Gestion du pipeline GStreamer pour Hailo"""
    
    @staticmethod
    def create_detection_pipeline(width: int, height: int, hef_path: str, camera_index: int):
        """
        Crée le pipeline de détection (Caméra CSI 0)
        Ce pipeline utilise l'IA et se termine par fakesink (aucune sortie vidéo).
        """
        pipeline_str = f"""
            rpicamsrc camera-num={camera_index} !
            video/x-raw,width={width},height={height},framerate=30/1 !
            videoconvert !
            queue max-size-buffers=1 leaky=downstream !
            hailonet hef-path={hef_path} !
            queue max-size-buffers=1 leaky=downstream !
            hailofilter name=hailo_filter !
            fakesink
        """
        
        print(f"🛠️ Pipeline Détection (CSI {camera_index}) créé")
        print(f"   Modèle: {hef_path}")
        print(f"   Résolution: {width}x{height}")
        
        return Gst.parse_launch(pipeline_str)

    @staticmethod
    def create_streaming_pipeline(width: int, height: int, camera_index: int):
        """
        Crée le pipeline de streaming (Caméra CSI 1 - Motorisée)
        Ce pipeline envoie les frames à l'appsink pour le VideoRecorder.
        """
        pipeline_str = f"""
            rpicamsrc camera-num={camera_index} !
            video/x-raw,width={width},height={height},framerate=30/1 !
            videoconvert !
            queue max-size-buffers=1 leaky=downstream !
            appsink name=streaming_sink emit-signals=true sync=false max-buffers=1 drop=true
        """
        
        print(f"🛠️ Pipeline Streaming (CSI {camera_index}) créé")
        print(f"   Résolution: {width}x{height}")
        print(f"   Appsink: streaming_sink")
        
        return Gst.parse_launch(pipeline_str)
    
    @staticmethod
    def create_single_camera_pipeline(width: int, height: int, camera_index: int, hef_path: str = None):
        """
        Crée un pipeline unique avec à la fois streaming et détection.
        Utilise une seule caméra pour les deux fonctionnalités.
        """
        if hef_path:
            # Pipeline avec détection
            pipeline_str = f"""
                rpicamsrc camera-num={camera_index} !
                video/x-raw,width={width},height={height},framerate=30/1 !
                videoconvert !
                tee name=t !
                queue !
                videoscale !
                video/x-raw,width={width},height={height} !
                appsink name=streaming_sink emit-signals=true sync=false max-buffers=1 drop=true
                t. !
                queue !
                hailonet hef-path={hef_path} !
                queue !
                hailofilter name=hailo_filter !
                fakesink
            """
            print(f"🛠️ Pipeline Unique (CSI {camera_index}) avec détection créé")
        else:
            # Pipeline sans détection
            pipeline_str = f"""
                rpicamsrc camera-num={camera_index} !
                video/x-raw,width={width},height={height},framerate=30/1 !
                videoconvert !
                appsink name=streaming_sink emit-signals=true sync=false max-buffers=1 drop=true
            """
            print(f"🛠️ Pipeline Unique (CSI {camera_index}) sans détection créé")
        
        return Gst.parse_launch(pipeline_str)
    
    @staticmethod
    def get_pipeline_status(pipeline):
        """Retourne le statut d'un pipeline"""
        try:
            state_change_return, state, pending = pipeline.get_state(Gst.CLOCK_TIME_NONE)
            
            state_names = {
                Gst.State.VOID_PENDING: "VOID_PENDING",
                Gst.State.NULL: "NULL",
                Gst.State.READY: "READY",
                Gst.State.PAUSED: "PAUSED",
                Gst.State.PLAYING: "PLAYING"
            }
            
            return {
                "state": state_names.get(state, "UNKNOWN"),
                "change_return": state_change_return.value_nick,
                "pending": state_names.get(pending, "NONE")
            }
        except Exception as e:
            return {"error": str(e)}
    
    @staticmethod
    def print_pipeline_info(pipeline):
        """Affiche des informations sur un pipeline"""
        print("\n" + "="*50)
        print("INFORMATION DU PIPELINE")
        print("="*50)
        
        status = HailoPipeline.get_pipeline_status(pipeline)
        print(f"État: {status['state']}")
        print(f"Changement: {status['change_return']}")
        
        # Lister les éléments
        print("\nÉléments du pipeline:")
        pipeline.iterate_elements().foreach(
            lambda element, _: print(f"  - {element.get_name()}: {type(element).__name__}"),
            None
        )
        
        print("="*50)