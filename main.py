import os
import sys
from pathlib import Path
import uvicorn

from engine.audio_engine import AudioEngine
from services.project_service import ProjectService
from web.server import create_app

def main():
    base_dir = Path(__file__).parent
    projects_dir = base_dir / "projects"

    print("=" * 60)
    print("   BSplayer - Standalone Multitrack Backing Track Player")
    print("   Inspired by M-Live B.Beat Architecture")
    print("=" * 60)

    # 1. Initialize Audio Engine
    print("\n[1/3] Inicializando Motor de Audio Multicanal...")
    engine = AudioEngine(sample_rate=48000, blocksize=512)

    # 2. Initialize Project Service
    print("\n[2/3] Verificando proyectos y biblioteca de canciones...")
    project_service = ProjectService(projects_dir)
    projects = project_service.list_projects()

    if not projects:
        print("[ProjectService] Creando proyecto de demostración con 4 salidas...")
        demo_project = project_service.create_demo_project()
        print(f"[ProjectService] Proyecto '{demo_project.title}' generado con éxito.")
        active_project = demo_project
    else:
        active_project = project_service.get_project(projects[0]["id"])

    # Load active project into audio engine
    if active_project:
        print(f"[AudioEngine] Cargando pistas del proyecto: '{active_project.title}'")
        engine.load_project(active_project, project_service.get_project_dir(active_project.id))

    # 3. Initialize Hardware Controller (Buttons, Knobs, OLED)
    print("\n[3/4] Inicializando Controladores Físicos (GPIO, Encoders, OLED)...")
    from hardware.hardware_manager import HardwareManager

    def on_play_pause():
        if engine.is_playing:
            engine.pause()
        else:
            engine.play()

    def on_stop():
        engine.stop()

    def on_volume_change(delta: float):
        new_vol = max(0.0, min(engine.master_volume + delta, 1.5))
        engine.set_master_volume(new_vol)
        print(f"[Hardware] Master Volume: {int(new_vol * 100)}%")

    hw = HardwareManager(
        on_play_pause=on_play_pause,
        on_stop=on_stop,
        on_volume_change=on_volume_change,
        get_status_fn=engine.get_status
    )
    hw.start_display_loop()

    # 4. Create Web Application
    print("\n[4/4] Iniciando Servidor Web y API de Control Remoto...")
    app = create_app(engine, project_service)

    port = 8000
    host = "0.0.0.0" # Accessible from any mobile/tablet on local Wi-Fi
    print(f"\n" + "=" * 60)
    print(f"   BSplayer listo y activo!")
    print(f"   -> Panel Local:       http://localhost:{port}")
    print(f"   -> Control en Escena: http://<IP_DE_TU_PC>:{port}")
    print("=" * 60 + "\n")

    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    main()
