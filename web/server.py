import asyncio
import json
import zipfile
import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from engine.audio_engine import AudioEngine
from services.project_service import ProjectService

def create_app(engine: AudioEngine, project_service: ProjectService) -> FastAPI:
    app = FastAPI(title="BSplayer - Multitrack Backing Track Player")

    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)

    # Active WebSocket clients for live telemetry (VU meters, timestamps)
    active_websockets = set()

    # Pydantic schemas
    class PlaybackSeekRequest(BaseModel):
        seconds: float

    class DeviceSelectRequest(BaseModel):
        device_id: int
        channels: Optional[int] = None

    class TrackUpdateRequest(BaseModel):
        track_id: str
        volume: Optional[float] = None
        mute: Optional[bool] = None
        solo: Optional[bool] = None
        output_channel: Optional[int] = None

    class MasterVolumeRequest(BaseModel):
        volume: float

    class LoadProjectRequest(BaseModel):
        project_id: str

    @app.get("/api/status")
    def get_status():
        return engine.get_status()

    @app.get("/api/devices")
    def get_devices():
        return engine.get_available_devices()

    @app.post("/api/device/select")
    def select_device(req: DeviceSelectRequest):
        engine.set_device(req.device_id, req.channels)
        return {"status": "ok", "device_index": req.device_id, "channels": engine.num_output_channels}

    @app.get("/api/projects")
    def list_projects():
        return project_service.list_projects()

    @app.get("/api/projects/current")
    def get_current_project():
        if engine.current_project:
            return engine.current_project.to_dict()
        return None

    @app.get("/api/shows")
    def list_shows():
        return project_service.list_shows()

    @app.post("/api/shows/save")
    def save_show(data: Dict[str, Any]):
        return project_service.save_show(data)

    @app.post("/api/projects/load")
    def load_project(req: LoadProjectRequest):
        proj = project_service.get_project(req.project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
        base_dir = project_service.get_project_dir(req.project_id)
        engine.load_project(proj, base_dir)
        return {"status": "ok", "project": proj.to_dict()}

    @app.post("/api/projects/upload")
    async def upload_bsp(file: UploadFile = File(...)):
        if not file.filename.lower().endswith(".bsp"):
            raise HTTPException(status_code=400, detail="Only .bsp files are supported")
        dest_path = project_service.root / file.filename
        content = await file.read()
        with open(dest_path, "wb") as f:
            f.write(content)
        return {"status": "ok", "filename": file.filename, "size_mb": round(len(content)/(1024*1024), 2)}

    @app.get("/api/video/{project_id}")
    def get_project_video(project_id: str):
        proj = project_service.get_project(project_id)
        if not proj or not proj.video_file:
            raise HTTPException(status_code=404, detail="No video found for project")
        base_path = project_service.get_project_path(project_id)
        if base_path.is_file() and base_path.suffix.lower() == ".bsp":
            cache_dir = project_service.root / ".cache" / project_id
            cache_dir.mkdir(parents=True, exist_ok=True)
            video_cached = cache_dir / proj.video_file
            if not video_cached.exists():
                with zipfile.ZipFile(base_path, 'r') as z:
                    for name in z.namelist():
                        if Path(name).name == Path(proj.video_file).name:
                            with z.open(name) as src, open(video_cached, "wb") as dst:
                                dst.write(src.read())
                            break
            if video_cached.exists():
                return FileResponse(video_cached, media_type="video/mp4")
        elif base_path.is_dir():
            v_path = base_path / proj.video_file
            if v_path.exists():
                return FileResponse(v_path, media_type="video/mp4")
        raise HTTPException(status_code=404, detail="Video file not found")

    @app.post("/api/playback/play")
    def play():
        engine.play()
        return {"status": "ok"}

    @app.post("/api/playback/pause")
    def pause():
        engine.pause()
        return {"status": "ok"}

    @app.post("/api/playback/stop")
    def stop():
        engine.stop()
        return {"status": "ok"}

    @app.post("/api/playback/seek")
    def seek(req: PlaybackSeekRequest):
        engine.seek(req.seconds)
        return {"status": "ok", "current_time": req.seconds}

    @app.post("/api/track/update")
    def update_track(req: TrackUpdateRequest):
        if req.volume is not None:
            engine.set_track_volume(req.track_id, req.volume)
        if req.mute is not None:
            engine.set_track_mute(req.track_id, req.mute)
        if req.solo is not None:
            engine.set_track_solo(req.track_id, req.solo)
        if req.output_channel is not None:
            engine.set_track_output(req.track_id, req.output_channel)

        # Save changes to project file
        if engine.current_project:
            project_service.save_project(engine.current_project)

        return {"status": "ok"}

    @app.post("/api/master/volume")
    def set_master_volume(req: MasterVolumeRequest):
        engine.set_master_volume(req.volume)
        return {"status": "ok", "master_volume": req.volume}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        active_websockets.add(websocket)
        try:
            while True:
                # Keep connection alive, listen for client heartbeat
                data = await websocket.receive_text()
        except WebSocketDisconnect:
            active_websockets.remove(websocket)
        except Exception:
            if websocket in active_websockets:
                active_websockets.remove(websocket)

    # Background task to broadcast status at 20fps
    @app.on_event("startup")
    async def start_broadcaster():
        async def broadcast_loop():
            while True:
                if active_websockets:
                    status = engine.get_status()
                    msg = json.dumps(status)
                    dead_sockets = set()
                    for ws in active_websockets:
                        try:
                            await ws.send_text(msg)
                        except Exception:
                            dead_sockets.add(ws)
                    for ds in dead_sockets:
                        active_websockets.remove(ds)
                await asyncio.sleep(0.05) # 20 updates per second

        asyncio.create_task(broadcast_loop())

    @app.get("/screen")
    def get_screen_ui():
        return FileResponse(str(static_dir / "screen.html"))

    # Serve static frontend
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
