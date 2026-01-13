"""
Module "Boîte à Outils" pour GStreamer
Ce fichier n'est pas utilisé directement par notre version actuelle du code,
mais il sert de bibliothèque de "recettes" pour construire des pipelines GStreamer.
Il centralise la syntaxe complexe de GStreamer, rendant le code principal
plus lisible et facile à maintenir.
Il a été utilisé lors des phases initiales de développement pour tester différentes
architectures de flux vidéo.
"""

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstApp', '1.0') # Nécessaire pour les éléments appsrc/appsink
from gi.repository import Gst

# ---DÉFINITION DE LA CLASSE UTILITAIRE ---
# Cette classe ne contient que des méthodes statiques (@staticmethod).
# On n'a jamais besoin de créer une instance de HailoPipeline.
# On l'utilise comme une boîte à outils : HailoPipeline.create_detection_pipeline(...)
class HailoPipeline:
    """Gestion des chaînes de commande (pipelines) GStreamer."""
    
    # ---PIPELINES SPÉCIFIQUES ---

    @staticmethod
    def create_detection_pipeline(width: int, height: int, hef_path: str, camera_index: int):
        """
        Crée le pipeline pour la Caméra 0 (Perception).
        Ce pipeline est "headless" : il capture la vidéo, l'envoie à l'IA,
        mais ne produit aucune sortie vidéo visible.
        """
        # La chaîne de commande GStreamer, lue de gauche à droite. Le '!' connecte les éléments.
        pipeline_str = f"""
            rpicamsrc camera-num={camera_index} !  # Source : la caméra Raspberry Pi
            video/x-raw,width={width},height={height},framerate=30/1 ! # Définit le format de la vidéo
            videoconvert ! # Convertit le format de couleur si nécessaire
            
            # Élément de bufferisation pour la performance. Évite la latence si l'IA est lente.
            queue max-size-buffers=1 leaky=downstream ! 
            
            hailonet hef-path={hef_path} ! # Cœur de l'IA : exécute le modèle sur la puce Hailo
            
            queue max-size-buffers=1 leaky=downstream ! # Autre buffer
            
            hailofilter name=hailo_filter ! # Formate les résultats de l'IA pour qu'on puisse les lire
            
            fakesink # La fin du pipeline : un "puits sans fond" qui jette les images,
                     # car on ne veut que les données de détection, pas la vidéo elle-même.
        """
        
        print(f"🛠️ Pipeline Détection (CSI {camera_index}) créé")
        print(f"   Modèle: {hef_path}")
        print(f"   Résolution: {width}x{height}")
        
        # Gst.parse_launch transforme cette chaîne de texte en un véritable objet pipeline GStreamer.
        return Gst.parse_launch(pipeline_str)

    @staticmethod
    def create_streaming_pipeline(width: int, height: int, camera_index: int):
        """
        Crée le pipeline pour la Caméra 1 (Action/Diffusion).
        Ce pipeline envoie les images capturées à notre code Python pour traitement.
        """
        pipeline_str = f"""
            rpicamsrc camera-num={camera_index} !
            video/x-raw,width={width},height={height},framerate=30/1 !
            videoconvert !
            queue max-size-buffers=1 leaky=downstream !
            
            # La fin du pipeline : un "récepteur" qui sort les images du monde GStreamer
            # pour les donner à notre application Python. C'est le pont vers notre code.
            appsink name=streaming_sink emit-signals=true sync=false max-buffers=1 drop=true
        """
        
        print(f"🛠️ Pipeline Streaming (CSI {camera_index}) créé")
        print(f"   Résolution: {width}x{height}")
        print(f"   Appsink: streaming_sink")
        
        return Gst.parse_launch(pipeline_str)
    
    @staticmethod
    def create_single_camera_pipeline(width: int, height: int, camera_index: int, hef_path: str = None):
        """
        Crée un pipeline HYBRIDE pour un système à une seule caméra.
        Le flux vidéo est dupliqué pour faire à la fois de la détection ET du streaming.
        """
        if hef_path:
            # Cas où la détection est activée
            pipeline_str = f"""
                rpicamsrc camera-num={camera_index} !
                video/x-raw,width={width},height={height},framerate=30/1 !
                videoconvert !
                
                # L'élément "tee" est un "T" de plomberie : il duplique le flux en deux branches.
                tee name=t !
                
                # Branche 1 : Streaming vers le code Python
                queue !
                appsink name=streaming_sink ... !
                
                # Branche 2 : Détection IA en arrière-plan
                t. !
                queue !
                hailonet hef-path={hef_path} !
                hailofilter name=hailo_filter !
                fakesink
            """
            print(f"🛠️ Pipeline Unique (CSI {camera_index}) avec détection créé")
        else:
            # Cas simple sans détection
            pipeline_str = f"""
                rpicamsrc camera-num={camera_index} ! ... ! appsink name=streaming_sink ...
            """
            print(f"🛠️ Pipeline Unique (CSI {camera_index}) sans détection créé")
        
        return Gst.parse_launch(pipeline_str)
    
    # ---OUTILS DE DÉBOGAGE ---
    
    @staticmethod
    def get_pipeline_status(pipeline):
        """Fonction utilitaire pour interroger l'état d'un pipeline (Joué, Pause, etc.)."""
        try:
            # Demande à GStreamer l'état actuel du pipeline
            _, state, _ = pipeline.get_state(Gst.CLOCK_TIME_NONE)
            
            # Traduction de l'état technique en texte lisible
            state_names = {
                Gst.State.NULL: "NULL (Arrêté)",
                Gst.State.READY: "READY (Prêt)",
                Gst.State.PAUSED: "PAUSED (En Pause)",
                Gst.State.PLAYING: "PLAYING (En Lecture)"
            }
            
            return state_names.get(state, "UNKNOWN (Inconnu)")
        except Exception as e:
            return f"Erreur: {str(e)}"
    
    @staticmethod
    def print_pipeline_info(pipeline):
        """Affiche un résumé complet d'un pipeline pour le débogage."""
        print("\n" + "="*50)
        print("INFORMATION DU PIPELINE")
        print("="*50)
        
        # Affiche l'état (Joué, Pause, etc.)
        status = HailoPipeline.get_pipeline_status(pipeline)
        print(f"État: {status}")
        
        # Affiche la liste de tous les éléments qui composent le pipeline
        print("\nÉléments du pipeline:")
        iterator = pipeline.iterate_elements()
        # La syntaxe "next(iterator, None)" est une manière propre de parcourir les éléments
        element = iterator.next()
        while element:
            print(f"  - {element.get_name()}")
            element = iterator.next()
            
        print("="*50)