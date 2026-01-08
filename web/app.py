"""
Serveur Web Flask pour le streaming
"""

import threading
from flask import Flask
from web.routes import register_routes

class WebServer:
    def __init__(self, video_recorder, config, hailo_system):
        self.video_recorder = video_recorder
        self.config = config
        self.hailo_system = hailo_system  # Pour accès aux données du détecteur
        self.app = None
        self.server_thread = None
        self.running = False
    
    def start(self):
        """Démarre le serveur web"""
        print("🌐 Démarrage du serveur web...")
        
        self.app = Flask(__name__)
        
        # Enregistrement des routes avec hailo_system
        register_routes(self.app, self.video_recorder, self.config, self.hailo_system)
        
        # Démarrage dans un thread séparé
        self.running = True
        self.server_thread = threading.Thread(
            target=self._run_server, 
            daemon=True
        )
        self.server_thread.start()
        
        print(f"✅ Serveur web démarré sur {self.config.get_server_url()}")
    
    def stop(self):
        """Arrête le serveur web"""
        self.running = False
        if self.server_thread:
            # Pour s'assurer que le thread se termine proprement 
            self.server_thread.join(timeout=1) 
    
    def _run_server(self):
        """Exécute le serveur Flask"""
        try:
            self.app.run(
                host=self.config.web.host,
                port=self.config.web.port,
                threaded=True,
                debug=False,
                use_reloader=False # Important pour l'embarqué
            )
        except Exception as e:
             print(f"❌ Erreur Serveur Web: {e}")