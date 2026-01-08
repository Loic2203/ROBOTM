import time
import os
import glob
import cv2
from datetime import datetime
import traceback
from flask import (
    Response, jsonify, render_template_string,
    send_file, request, redirect, url_for
)
import pathlib

# Templates
from web.templates import HTML_TEMPLATE, ARCHIVE_TEMPLATE, PREVIEW_TEMPLATE

# Chemin racine du projet 
PROJECT_ROOT = pathlib.Path(__file__).parent.parent.resolve()

# Variables globales initialisées par register_routes()
video_recorder = None
config = None
hailo_system = None


def register_routes(app, vr, cfg, hs):
    global video_recorder, config, hailo_system
    video_recorder = vr
    config = cfg
    hailo_system = hs

    # Dossier des miniatures
    THUMB_DIR = os.path.join(config.recording.output_dir, 'thumbs')
    os.makedirs(THUMB_DIR, exist_ok=True)

    # ROUTES DE BASE (STREAMING & CONTRÔLE)

    @app.route('/')
    def index():
        return render_template_string(HTML_TEMPLATE)

    @app.route('/stream')
    def stream():
        def gen():
            while True:
                frame = video_recorder.get_frame_jpeg()
                if frame:
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                time.sleep(0.033)  # ~30 FPS
        return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

    @app.route('/status')
    def status():
        try:
            rec_status = video_recorder.get_record_status()
            state = rec_status.get('state', 'stopped')
        except:
            state = 'stopped'

        if hailo_system:
            det = hailo_system.detector.get_detection_status()
            zoom = getattr(hailo_system, 'current_zoom', 1.0)
            pan = getattr(hailo_system, 'current_pan_angle', 90)
        else:
            det = {'mode': 'Désactivé', 'person_count': 0, 'ball_detected': False}
            zoom = 1.0
            pan = 90

        return jsonify({
            'fps': 30,
            'state': state,
            'stream_status': 'active',
            'recording_mode': 'local',
            'video_format': 'MP4/H.264',
            'current_zoom': round(zoom, 1),
            'pan_angle': int(pan),
            'detection_mode': det['mode'],
            'person_count': det['person_count'],
            'ball_detected': det['ball_detected']
        })

    @app.route('/start_record', methods=['POST'])
    def start():
        video_recorder.start_recording()
        return jsonify({"status": "ok", "message": "Enregistrement démarré"})

    @app.route('/pause_record', methods=['POST'])
    def pause():
        video_recorder.pause_recording()
        return jsonify({"status": "ok"})

    @app.route('/resume_record', methods=['POST'])
    def resume():
        video_recorder.resume_recording()
        return jsonify({"status": "ok"})

    @app.route('/stop_record', methods=['POST'])
    def stop():
        video_recorder.stop_recording()
        return jsonify({"status": "ok"})

    @app.route('/capture_clip', methods=['POST'])
    def clip():
        if video_recorder.clip_running:
            return jsonify({"status": "error", "message": "Clip déjà en cours"}), 409
        video_recorder.capture_clip()
        return jsonify({"status": "ok", "message": "Clip capturé"})

    # ROUTES ARCHIVES

    @app.route('/archive')
    def archive():
        output_dir_abs = PROJECT_ROOT / config.recording.output_dir
        search_path = str(output_dir_abs / f"*{config.recording.file_extension}")
        all_files = glob.glob(search_path)

        files_data = []

        for path in sorted(all_files, key=os.path.getctime, reverse=True):
            filename = os.path.basename(path)
            thumb_filename = f"{os.path.splitext(filename)[0]}.jpg"
            thumb_path_abs = PROJECT_ROOT / THUMB_DIR / thumb_filename

            if not os.path.exists(thumb_path_abs):
                video_recorder.generate_thumbnail(path, str(thumb_path_abs))

            thumb_url = url_for('get_thumbnail', filename=thumb_filename)

            try:
                size_mb = os.path.getsize(path) / (1024 * 1024)
                creation_date = datetime.fromtimestamp(os.path.getctime(path)).strftime('%Y-%m-%d %H:%M')

                file_html = f"""
                <div class="file-item">
                    <div class="thumbnail-container">
                        <img class="file-thumbnail" src="{thumb_url}" 
                             onerror="this.onerror=null;this.src='/static/no_thumb.jpg';"
                             alt="Miniature">
                    </div>
                    <div class="file-info">
                        <div class="file-name">{filename}</div>
                        <div class="file-meta">{creation_date} • {size_mb:.1f} MB</div>
                    </div>
                    <div class="file-actions">
                        <a href="{url_for('preview_video', filename=filename)}" class="action-btn preview-btn">Aperçu</a>
                        <a href="{url_for('download_file', filename=filename)}" class="action-btn download-btn">Télécharger</a>
                        <form method="POST" action="{url_for('delete_file', filename=filename)}" style="margin:0;">
                            <button type="submit" class="action-btn delete-btn"
                                    onclick="return confirm('Supprimer {filename} ?');">Supprimer</button>
                        </form>
                    </div>
                </div>
                """
                files_data.append(file_html)
            except Exception as e:
                print(f"Erreur traitement {filename}: {e}")

        return render_template_string(ARCHIVE_TEMPLATE, files_html="".join(files_data))

    @app.route('/download/<filename>')
    def download_file(filename):
        video_path = PROJECT_ROOT / config.recording.output_dir / filename
        if video_path.exists():
            return send_file(str(video_path), as_attachment=True)
        return "Fichier non trouvé", 404

    @app.route('/delete/<filename>', methods=['POST'])
    def delete_file(filename):
        video_path = PROJECT_ROOT / config.recording.output_dir / filename
        thumb_filename = f"{os.path.splitext(filename)[0]}.jpg"
        thumb_path = PROJECT_ROOT / THUMB_DIR / thumb_filename

        if video_path.exists():
            try:
                os.remove(video_path)
                if thumb_path.exists():
                    os.remove(thumb_path)
                return redirect(url_for('archive'))
            except Exception as e:
                return f"Erreur suppression: {e}", 500
        return "Fichier non trouvé", 404

    @app.route('/thumbs/<filename>')
    def get_thumbnail(filename):
        thumb_path = PROJECT_ROOT / THUMB_DIR / filename
        if thumb_path.exists():
            return send_file(str(thumb_path), mimetype='image/jpeg')
        return "Miniature manquante", 404


    # ROUTES LECTEUR VIDÉO HYBRIDE (Lecture + Frame-par-frame)

    @app.route('/preview/<filename>')
    def preview_video(filename):
        video_path = PROJECT_ROOT / config.recording.output_dir / filename
        if not video_path.exists():
            return "Vidéo non trouvée", 404
        return render_template_string(PREVIEW_TEMPLATE, filename=filename)

    @app.route('/video/<filename>')
    def serve_video(filename):
        """
        Route critique : permet la lecture fluide dans <video>
     
        """
        video_path = PROJECT_ROOT / config.recording.output_dir / filename
        path_str = str(video_path.resolve())

        if not os.path.exists(path_str):
            return "Fichier introuvable", 404

        # Détection intelligente du type MIME
        if filename.lower().endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.lower().endswith('.avi'):
            mimetype = 'video/x-msvideo'   # Fonctionne sur Chrome/Firefox/Edge
        else:
            mimetype = 'application/octet-stream'

        return send_file(
            path_str,
            mimetype=mimetype,
            as_attachment=False,
            conditional=True,      # Supporte barre de progression
            max_age=0
        )

    # Routes legacy (conservées pour compatibilité, mais plus utilisées par le nouveau lecteur)
    @app.route('/video_metadata/<filename>')
    def video_metadata(filename):
        video_path = PROJECT_ROOT / config.recording.output_dir / filename
        try:
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                return jsonify({"status": "error"}), 404
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            return jsonify({"status": "ok", "frame_count": frame_count, "fps": round(fps, 1)})
        except:
            return jsonify({"status": "error"}), 500

    @app.route('/get_frame/<filename>/<int:frame_index>')
    def get_frame(filename, frame_index):
        video_path = PROJECT_ROOT / config.recording.output_dir / filename
        frame_data, error = video_recorder.get_video_frame(str(video_path), frame_index)
        if frame_data:
            return Response(frame_data, mimetype='image/jpeg')
        return jsonify({"status": "error", "message": error or "Frame non trouvée"}), 404