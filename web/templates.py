
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Hailo B.BALL Tracker</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
        /* CSS OPTIMISÉ POUR TABLETTE ET GRAND ÉCRAN */
        * { 
            margin: 0; 
            padding: 0; 
            box-sizing: border-box; 
        }
        
        :root {
            --primary-bg: #121212;
            --secondary-bg: #1e1e1e;
            --accent-green: #4CAF50;
            --accent-red: #F44336;
            --accent-blue: #2196F3;
            --accent-orange: #FF9800;
            --text-primary: #ffffff;
            --border-radius: 12px;
        }
        
        body {
            font-family: 'Inter', sans-serif;
            background: var(--primary-bg);
            color: var(--text-primary);
            height: 100vh;
            overflow: hidden; 
        }
        
        .app-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            width: 100%;
            height: 100vh; 
            padding: 10px; 
        }

        .header {
            padding: 10px;
            margin-bottom: 10px; 
            font-size: 1.2rem;
            font-weight: 700;
            letter-spacing: 2px;
            color: var(--accent-green);
            display: flex; 
            justify-content: space-between;
            align-items: center;
            width: 100%;
            max-width: 1200px; 
        }
        
        .archive-link {
            text-decoration: none;
            color: var(--text-primary);
            padding: 8px 12px;
            border-radius: 8px;
            background: #34495e; 
            font-size: 0.9rem;
            transition: background-color 0.2s;
        }

        .archive-link:hover {
            background-color: #2c3e50;
        }

        .video-container {
            width: 100%;
            flex-grow: 1; 
            max-width: 1200px; 
            background: #000;
            border-radius: var(--border-radius);
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.7);
            overflow: hidden; 
        }
        
        #videoStream {
            width: 100%;
            height: 100%; 
            object-fit: contain; 
            display: block;
            border-radius: var(--border-radius);
        }

        .status-bar {
            width: 100%;
            max-width: 1200px; 
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            font-size: 1rem;
        }

        .status-item {
            display: flex;
            align-items: center;
        }

        .status-dot {
            height: 12px;
            width: 12px;
            border-radius: 50%;
            margin-right: 10px;
        }

        .status-dot.stopped { background: var(--accent-blue); }
        .status-dot.recording { background: var(--accent-red); animation: pulse-red 1s infinite; }
        .status-dot.paused { background: var(--accent-orange); }
        
        @keyframes pulse-red {
            0% { box-shadow: 0 0 0 0 rgba(244, 67, 54, 0.7); }
            70% { box-shadow: 0 0 0 10px rgba(244, 67, 54, 0); }
            100% { box-shadow: 0 0 0 0 rgba(244, 67, 54, 0); }
        }

        .controls {
            width: 100%;
            max-width: 1200px; 
            padding: 15px 0;
            display: flex;
            gap: 15px;
            justify-content: center;
        }

        .control-group {
            display: flex;
            gap: 15px;
            flex-grow: 1;
            max-width: 600px;
        }

        .btn {
            padding: 15px 10px;
            border-radius: var(--border-radius);
            font-size: 1.1rem;
            font-weight: 700;
            cursor: pointer;
            border: none;
            transition: background-color 0.2s, opacity 0.2s;
            flex-grow: 1;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .btn i { margin-right: 8px; }

        .btn.start { background-color: var(--accent-green); color: var(--text-primary); }
        .btn.stop { background-color: var(--accent-red); color: var(--text-primary); }
        .btn.pause { background-color: var(--accent-orange); color: var(--text-primary); }
        .btn.clip { background-color: var(--accent-blue); color: var(--text-primary); max-width: 250px; } 

        .btn:disabled { 
            background-color: #333 !important; 
            color: #666 !important; 
            cursor: not-allowed; 
            opacity: 0.6;
        }

        /* Media Query pour les petits écrans (tablette en mode portrait) */
        @media (max-width: 768px) {
            .control-group, .controls {
                flex-direction: column;
                gap: 10px;
            }
            .btn {
                width: 100%;
                max-width: none;
                padding: 20px 10px; 
            }
        }
    </style>
</head>
<body>
    <div class="app-container">
        <div class="header">
            <span>HAILO B.BALL TRACKER</span>
            <a href="/archive" class="archive-link"><i class="fas fa-archive"></i> ARCHIVES</a>
        </div>
        
        <div class="video-container">
            <img id="videoStream" src="/stream" alt="Live Video Stream">
        </div>

        <div class="status-bar">
            <div class="status-item">
                <span id="recordingStatusDot" class="status-dot stopped"></span>
                <strong id="recordingStatusText">Prêt</strong>
            </div>
            <div class="status-item">
                Mode : <span id="detectionModeText" style="margin-left: 5px; color: var(--accent-blue);">Initialisation</span>
            </div>
        </div>

        <div class="controls">
            <div class="control-group">
                <button id="startButton" class="btn start" onclick="handleStart()">
                    <i class="fas fa-play"></i> START
                </button>
                <button id="pauseResumeButton" class="btn pause" disabled onclick="handlePauseResume()">
                    <i class="fas fa-pause"></i> PAUSE
                </button>
                <button id="stopButton" class="btn stop" disabled onclick="handleStop()">
                    <i class="fas fa-stop"></i> STOP
                </button>
            </div>
            
            <button id="clipButton" class="btn clip" disabled onclick="handleClip()">
                <i class="fas fa-bolt"></i> CLIP (5s Pre-Roll)
            </button>
        </div>
    </div>

    <script>
        const STATUS_MAPPING = {
            'stopped': { text: 'PRÊT', dotClass: 'stopped', pauseIcon: 'fas fa-pause' },
            'recording': { text: 'EN COURS', dotClass: 'recording', pauseIcon: 'fas fa-pause' },
            'paused': { text: 'EN PAUSE', dotClass: 'paused', pauseIcon: 'fas fa-play' },
            'clip': { text: 'CLIP SAUV.', dotClass: 'clip' }
        };

        function sendCommand(endpoint) {
            return fetch('/' + endpoint, { method: 'POST' })
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`Erreur serveur (${response.status}) pour /${endpoint}`);
                    }
                    return response.json();
                })
                .catch(error => {
                    console.error('Erreur de commande:', error);
                    alert("Erreur de connexion/serveur : Impossible d'exécuter la commande. Vérifiez les logs du terminal.");
                    updateStatus(); 
                    throw error;
                });
        }
        
        function startRecording() { sendCommand('start_record'); }
        function stopRecording() { sendCommand('stop_record'); }
        function captureClip() { sendCommand('capture_clip'); }
        function pauseRecording() { sendCommand('pause_record'); }
        function resumeRecording() { sendCommand('resume_record'); }

        function handleStart() { startRecording(); }
        function handleStop() { stopRecording(); }
        function handleClip() { captureClip(); }
        
        function handlePauseResume() {
            const statusText = document.getElementById('recordingStatusText').textContent;
            if (statusText === 'EN COURS') {
                pauseRecording();
            } else if (statusText === 'EN PAUSE') {
                resumeRecording();
            }
        }

        function updateStatus() {
            fetch('/status')
                .then(response => {
                    if (!response.ok) throw new Error('Status fetch failed');
                    return response.json();
                })
                .then(data => {
                    const currentState = data.state;
                    const statusData = STATUS_MAPPING[currentState] || STATUS_MAPPING['stopped'];
                    
                    document.getElementById('recordingStatusText').textContent = statusData.text;
                    document.getElementById('recordingStatusDot').className = 'status-dot ' + statusData.dotClass;
                    document.getElementById('detectionModeText').textContent = data.detection_mode;
                    
                    const pauseResumeBtn = document.getElementById('pauseResumeButton');
                    pauseResumeBtn.innerHTML = `<i class="${statusData.pauseIcon}"></i> ${currentState === 'paused' ? 'REPRENDRE' : 'PAUSE'}`;

                    const isStopped = currentState === 'stopped';

                    document.getElementById('startButton').disabled = !isStopped;
                    document.getElementById('stopButton').disabled = isStopped;
                    document.getElementById('pauseResumeButton').disabled = isStopped;
                    document.getElementById('clipButton').disabled = isStopped;
                })
                .catch(error => {
                    document.getElementById('recordingStatusText').textContent = 'Erreur Conn. !';
                    document.getElementById('recordingStatusDot').className = 'status-dot stopped';
                    document.getElementById('startButton').disabled = false; 
                    document.getElementById('stopButton').disabled = true;
                    document.getElementById('pauseResumeButton').disabled = true;
                    document.getElementById('clipButton').disabled = true;
                });
        }
        
        window.addEventListener('load', () => {
            setInterval(updateStatus, 1500); 
            updateStatus();
        });
    </script>
</body>
</html>
"""

ARCHIVE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Archives Vidéo (HAILO B.BALL)</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
        :root {
            --primary-bg: #121212;
            --secondary-bg: #1e1e1e;
            --accent-green: #4CAF50;
            --accent-red: #F44336;
            --accent-blue: #2196F3;
            --text-primary: #ffffff;
            --border-radius: 8px;
        }
        body {
            font-family: 'Inter', sans-serif;
            background: var(--primary-bg);
            color: var(--text-primary);
        }
        .container {
            max-width: 1200px; 
            margin: 0 auto;
            padding: 20px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid var(--secondary-bg);
        }
        .header a {
            text-decoration: none;
            color: var(--accent-blue);
            font-weight: 700;
        }
        h1 {
            font-size: 1.8rem;
        }
        .file-grid { 
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            list-style: none;
            padding: 0;
        }
        .file-item {
            background: var(--secondary-bg);
            border-radius: var(--border-radius);
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.5);
            overflow: hidden;
            transition: transform 0.2s;
        }
        .file-item:hover {
            transform: translateY(-3px);
        }
        .thumbnail-container {
            width: 100%;
            height: 170px; 
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #000;
        }
        .file-thumbnail {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }
        .file-info {
            padding: 15px;
        }
        .file-name {
            font-weight: 700;
            font-size: 1.1rem;
            word-break: break-word;
            margin-bottom: 5px;
        }
        .file-meta {
            font-size: 0.8rem;
            color: #ccc;
        }
        .file-actions {
            display: flex;
            gap: 10px;
            padding: 15px;
            border-top: 1px solid #333;
        }
        .action-btn {
            padding: 10px 15px;
            border: none;
            border-radius: var(--border-radius);
            color: var(--text-primary);
            cursor: pointer;
            font-size: 0.9rem;
            text-decoration: none;
            white-space: nowrap; 
            flex-grow: 1;
            text-align: center;
            transition: opacity 0.2s;
        }
        .preview-btn { background: var(--accent-blue); }
        .download-btn { background: var(--accent-green); }
        .delete-btn { background: var(--accent-red); }
        
        .action-btn:hover { opacity: 0.8; }
        
        @media (max-width: 600px) {
            .file-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><i class="fas fa-archive"></i> Archives Vidéo</h1>
            <a href="/"><i class="fas fa-chevron-left"></i> Retour au Direct</a>
        </div>
        
        <div class="file-grid">
            {{ files_html | safe }} {% if not files_html %}
            <div class="file-item" style="grid-column: 1 / -1; padding: 20px; text-align: center;">
                Aucun enregistrement ou clip trouvé.
            </div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

PREVIEW_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ filename }} • HAILO B.BALL</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
        :root {
            --primary: #121212;
            --secondary: #1e1e1e;
            --green: #4CAF50;
            --blue: #2196F3;
            --text: #ffffff;
            --radius: 12px;
        }
        body { margin:0; padding:20px; background:var(--primary); color:var(--text); font-family:'Inter',sans-serif; }
        .container { max-width:1100px; margin:0 auto; }
        .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; flex-wrap:wrap; gap:15px; }
        .header h1 { font-size:1.5rem; word-break:break-all; margin:0; }
        .back { color:var(--green); text-decoration:none; font-weight:700; }
        video { width:100%; border-radius:var(--radius); background:#000; box-shadow:0 8px 30px rgba(0,0,0,0.8); }
        .controls { margin-top:20px; background:var(--secondary); padding:15px; border-radius:var(--radius); display:flex; flex-wrap:wrap; gap:12px; justify-content:center; align-items:center; }
        .btn { padding:12px 20px; background:#333; color:white; border:none; border-radius:8px; cursor:pointer; display:flex; align-items:center; gap:8px; }
        .btn.play { background:var(--green); }
        .btn.frame { background:var(--blue); }
        input[type=number] { width:100px; padding:10px; text-align:center; background:#333; border:1px solid #555; border-radius:8px; color:white; }
        .info { margin-top:15px; text-align:center; color:#aaa; }
        @media (max-width:768px) { .controls { flex-direction:column; } .btn, input { width:100%; max-width:300px; } }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{{ filename }}</h1>
            <a href="/archive" class="back">Retour aux archives</a>
        </div>

        <video id="video" controls autoplay muted preload="metadata">
            <source src="/video/{{ filename }}" type="video/mp4">
            Navigateur non supporté.
        </video>

        <div class="controls">
            <button id="playBtn" class="btn play">Lecture</button>
            <button class="btn frame" onclick="step(-1)">-1</button>
            <input type="number" id="frameInput" value="0" min="0">
            <button class="btn frame" onclick="step(1)">+1</button>
        </div>

        <div class="info">
            Frame <span id="cur">0</span> / <span id="tot">…</span>
            • <span id="time">0:00</span> / <span id="dur">…</span>
            • <span id="fps">…</span> FPS
        </div>
    </div>

    <script>
        const video = document.getElementById('video');
        const playBtn = document.getElementById('playBtn');
        const frameInput = document.getElementById('frameInput');
        const curSpan = document.getElementById('cur');
        const totSpan = document.getElementById('tot');
        const timeSpan = document.getElementById('time');
        const durSpan = document.getElementById('dur');
        const fpsSpan = document.getElementById('fps');

        let fps = 30;

        function format(t) { const m=Math.floor(t/60); const s=Math.floor(t%60); return `${m}:${s.toString().padStart(2,'0')}`; }

        video.addEventListener('timeupdate', () => {
            const frame = Math.round(video.currentTime * fps);
            curSpan.textContent = frame;
            frameInput.value = frame;
            timeSpan.textContent = format(video.currentTime);
        });

        video.addEventListener('loadedmetadata', () => {
            fps = Math.round(video.duration * (video.webkitDecodedFrameCount || video.mozVideoDecodedByteRate || 30) / video.duration) || 30;
            const totalFrames = Math.round(video.duration * fps);
            totSpan.textContent = totalFrames;
            durSpan.textContent = format(video.duration);
            fpsSpan.textContent = fps;
        });

        playBtn.onclick = () => {
            if (video.paused) { video.play(); playBtn.innerHTML = 'Pause'; }
            else { video.pause(); playBtn.innerHTML = 'Lecture'; }
        };

        function step(frames) {
            video.pause();
            video.currentTime += frames / fps;
        }

        frameInput.onchange = () => {
            const f = parseInt(frameInput.value);
            if (!isNaN(f)) video.currentTime = f / fps;
        };

        // Raccourcis clavier
        document.onkeydown = e => {
            if (e.key===' ') { e.preventDefault(); playBtn.click(); }
            else if (e.key==='ArrowLeft') step(-1);
            else if (e.key==='ArrowRight') step(1);
        };
    </script>
</body>
</html>
"""

