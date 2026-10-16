-- ==============================================================================
-- ReaScript: Export_BSplayer_Project.lua
-- Autor: BSplayer Project
-- Descripción: Exporta el proyecto completo de REAPER a un archivo único .bsp
--              (BSplayer Package Container) para Raspberry Pi y PC:
--              - Renderiza stems de audio a 48kHz / 24-bit PCM Mono
--              - Espera de forma asíncrona a que REAPER termine el renderizado
--              - Extrae Marcadores de estructura (Intro, Verso, Coro, Puente, Outro)
--              - Extrae Letras y Acordes sincronizados (desde eventos MIDI o marcadores)
--              - Exporta automatizaciones MIDI (Program Changes, CC, DMX luces)
--              - Detecta y empaqueta video de fondo/pantalla (MP4, MOV, MKV)
--              - Empaqueta TODO en un único archivo [Canción].bsp sin carpetas sueltas
-- ==============================================================================

function Msg(val)
    reaper.ShowConsoleMsg(tostring(val) .. "\n")
end

function SanitizeFilename(str)
    if not str then return "stem" end
    return str:gsub('[\\/:%*%?"<>|]', '_'):gsub('%s+', '_'):gsub('^_+', ''):gsub('_+$', ''):lower()
end

function EscapeJSON(str)
    if not str then return "" end
    return str:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\r', '\\r'):gsub('\t', '\\t')
end

function CopyFile(src_path, dst_path)
    local infile = io.open(src_path, "rb")
    if not infile then return false end
    local outfile = io.open(dst_path, "wb")
    if not outfile then
        infile:close()
        return false
    end
    outfile:write(infile:read("*all"))
    infile:close()
    outfile:close()
    return true
end

-- 1. Buscar archivo de Video en la línea de tiempo del proyecto
function FindProjectVideo(proj)
    local tracks_count = reaper.CountTracks(proj)
    for t = 0, tracks_count - 1 do
        local tr = reaper.GetTrack(proj, t)
        local items_count = reaper.CountTrackMediaItems(tr)
        for i = 0, items_count - 1 do
            local item = reaper.GetTrackMediaItem(tr, i)
            local take = reaper.GetActiveTake(item)
            if take then
                local src = reaper.GetMediaItemTake_Source(take)
                if src then
                    local fn = reaper.GetMediaSourceFileName(src, "")
                    local ext = fn:match("%.([^%.]+)$")
                    if ext then
                        ext = ext:lower()
                        if ext == "mp4" or ext == "mov" or ext == "mkv" or ext == "avi" or ext == "webm" then
                            return fn
                        end
                    end
                end
            end
        end
    end
    return nil
end

-- 2. Extraer Letras y Acordes desde eventos MIDI
function ExtractLyricsFromMidi(proj)
    local lyrics = {}
    local tracks_count = reaper.CountTracks(proj)
    for t = 0, tracks_count - 1 do
        local tr = reaper.GetTrack(proj, t)
        local items_count = reaper.CountTrackMediaItems(tr)
        for i = 0, items_count - 1 do
            local item = reaper.GetTrackMediaItem(tr, i)
            local take = reaper.GetActiveTake(item)
            if take and reaper.TakeIsMIDI(take) then
                local _, _, _, num_textsyx = reaper.MIDI_CountEvts(take)
                for e = 0, num_textsyx - 1 do
                    local _, _, _, ppqpos, evt_type, msg = reaper.MIDI_GetTextSysexEvt(take, e)
                    -- evt_type 5 = Lyric, 1 = Text, 6 = Marker
                    if evt_type == 5 or evt_type == 1 or evt_type == 6 then
                        local time_sec = reaper.MIDI_GetProjTimeFromPPQPos(take, ppqpos)
                        local chord = msg:match("%[([A-G][^%]]*)%]")
                        local clean_text = msg:gsub("%[[^%]]*%]", ""):gsub("^%s+", ""):gsub("%s+$", "")
                        if clean_text ~= "" or chord then
                            table.insert(lyrics, {
                                time_seconds = time_sec,
                                text = clean_text ~= "" and clean_text or msg,
                                chords = chord and ("[" .. chord .. "]") or nil
                            })
                        end
                    end
                end
            end
        end
    end
    table.sort(lyrics, function(a, b) return a.time_seconds < b.time_seconds end)
    return lyrics
end

-- 3. Extraer Cues / Automatizaciones MIDI (Program Changes, CC, DMX triggers)
function ExtractMidiCues(proj)
    local cues = {}
    local tracks_count = reaper.CountTracks(proj)
    for t = 0, tracks_count - 1 do
        local tr = reaper.GetTrack(proj, t)
        local _, track_name = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
        local lower = track_name:lower()
        local is_cue_track = lower:find("midi") or lower:find("dmx") or lower:find("cue") or lower:find("pedal") or lower:find("patch") or lower:find("luz") or lower:find("luces")

        local items_count = reaper.CountTrackMediaItems(tr)
        for i = 0, items_count - 1 do
            local item = reaper.GetTrackMediaItem(tr, i)
            local take = reaper.GetActiveTake(item)
            if take and reaper.TakeIsMIDI(take) then
                local _, num_notes, num_ccevt, _ = reaper.MIDI_CountEvts(take)
                -- Program Changes & Control Changes
                for c = 0, num_ccevt - 1 do
                    local _, _, _, ppqpos, chanmsg, chan, msg2, msg3 = reaper.MIDI_GetCC(take, c)
                    local time_sec = reaper.MIDI_GetProjTimeFromPPQPos(take, ppqpos)
                    -- chanmsg: 192 = Program Change, 176 = Control Change
                    if chanmsg == 192 then
                        table.insert(cues, {
                            time_seconds = time_sec,
                            channel = chan + 1,
                            type = "program_change",
                            value = msg2,
                            comment = "Preset/Patch Ch." .. (chan + 1) .. " -> " .. msg2
                        })
                    elseif chanmsg == 176 then
                        table.insert(cues, {
                            time_seconds = time_sec,
                            channel = chan + 1,
                            type = "control_change",
                            cc = msg2,
                            value = msg3,
                            comment = "CC " .. msg2 .. " = " .. msg3 .. " (Ch." .. (chan + 1) .. ")"
                        })
                    end
                end
                -- Note Ons (DMX light triggers)
                if is_cue_track then
                    for n = 0, num_notes - 1 do
                        local _, _, _, startppq, _, chan, pitch, vel = reaper.MIDI_GetNote(take, n)
                        local time_sec = reaper.MIDI_GetProjTimeFromPPQPos(take, startppq)
                        table.insert(cues, {
                            time_seconds = time_sec,
                            channel = chan + 1,
                            type = "note_on",
                            note = pitch,
                            velocity = vel,
                            comment = "DMX/Trigger Note " .. pitch .. " Vel " .. vel
                        })
                    end
                end
            end
        end
    end
    table.sort(cues, function(a, b) return a.time_seconds < b.time_seconds end)
    return cues
end

function Main()
    local proj = 0 -- Proyecto actual
    local proj_name = reaper.GetProjectName(proj, "")
    if proj_name == "" then
        proj_name = "Nueva_Cancion"
    else
        proj_name = proj_name:gsub("%.RPP$", ""):gsub("%.rpp$", "")
    end

    local bpm = reaper.Master_GetTempo()
    local proj_len = reaper.GetProjectLength(proj)
    if proj_len <= 0 then
        reaper.MB("El proyecto no contiene elementos en la línea de tiempo o duración calculada.", "BSplayer Export Error", 0)
        return
    end

    -- Diálogo inicial con el usuario
    local default_dest = "D:\\Blas\\BSplayer\\projects"
    local retval, user_inputs = reaper.GetUserInputs(
        "Exportador BSP para BSplayer",
        4,
        "Título de Canción:,Artista / Banda:,Carpeta Destino:,Modo Render (1=Auto Silencioso, 2=Ventana):,extrawidth=220",
        proj_name .. ",Mi Banda," .. default_dest .. ",1"
    )
    if not retval then return end

    local song_title, artist_name, base_export_dir, render_mode_str = user_inputs:match("([^,]+),([^,]+),([^,]+),([^,]+)")
    if not song_title or not base_export_dir then return end

    local render_mode = tonumber(render_mode_str) or 1
    local song_id = SanitizeFilename(song_title)

    -- Carpetas de trabajo
    local final_bsp_file = base_export_dir .. "\\" .. song_id .. ".bsp"
    local staging_folder = base_export_dir .. "\\" .. song_id .. "_staging"

    reaper.RecursiveCreateDirectory(staging_folder, 0)

    reaper.ClearConsole()
    Msg("==================================================================")
    Msg("   BSPLAYER - EXPORTADOR DE PROYECTO A PAQUETE ÚNICO (.BSP)")
    Msg("   Canción: " .. song_title .. " | Artista: " .. artist_name)
    Msg("   Tempo:   " .. string.format("%.1f", bpm) .. " BPM | Duración: " .. string.format("%.1f", proj_len) .. "s")
    Msg("   Archivo Objetivo: " .. final_bsp_file)
    Msg("==================================================================")

    -- 1. Extraer Marcadores y Secciones
    Msg("\n[1/6] Analizando Marcadores y Regiones...")
    local markers = {}
    local num_markers = reaper.CountProjectMarkers(proj)
    for i = 0, num_markers - 1 do
        local _, is_region, pos, _, name, _ = reaper.EnumProjectMarkers3(proj, i)
        if name ~= "" then
            table.insert(markers, {
                name = name,
                time_seconds = pos
            })
            Msg(string.format("  * [%s] a los %.2fs", name, pos))
        end
    end
    table.sort(markers, function(a, b) return a.time_seconds < b.time_seconds end)

    -- 2. Extraer Letras y Acordes
    Msg("\n[2/6] Analizando Letras y Acordes sincronizados...")
    local lyrics = ExtractLyricsFromMidi(proj)
    if #lyrics > 0 then
        Msg(string.format("  -> Se detectaron %d eventos de letra en pistas MIDI.", #lyrics))
    else
        Msg("  -> No se detectaron letras en eventos MIDI. Generando tarjetas por marcador...")
        for _, m in ipairs(markers) do
            local chord = m.name:match("%[([A-G][^%]]*)%]")
            local text_clean = m.name:gsub("%[[^%]]*%]", ""):gsub("^%s+", ""):gsub("%s+$", "")
            table.insert(lyrics, {
                time_seconds = m.time_seconds,
                text = text_clean ~= "" and text_clean or ("Sección: " .. m.name),
                chords = chord and ("[" .. chord .. "]") or "[ Acorde ]"
            })
        end
    end

    -- 3. Extraer Cues MIDI / DMX
    Msg("\n[3/6] Escaneando automatizaciones y cambios de programa MIDI...")
    local midi_cues = ExtractMidiCues(proj)
    Msg(string.format("  -> Se encontraron %d eventos de disparo/preset MIDI.", #midi_cues))

    -- 4. Detectar Video
    Msg("\n[4/6] Buscando video en el proyecto...")
    local video_path = FindProjectVideo(proj)
    local video_filename = nil
    if video_path then
        local raw_vname = video_path:match("[^/\\]+$")
        video_filename = "video_" .. SanitizeFilename(raw_vname:gsub("%.[^%.]+$", "")) .. ".mp4"
        local v_dest = staging_folder .. "\\" .. video_filename
        Msg("  -> Video detectado: " .. video_path)
        Msg("  -> Copiando a contenedor: " .. video_filename .. " ...")
        CopyFile(video_path, v_dest)
    else
        Msg("  -> Sin pista de video.")
    end

    -- 5. Analizar Pistas y Preparar Stems
    Msg("\n[5/6] Configurando renderizado de pistas (48kHz 24-bit Mono)...")
    local tracks_count = reaper.CountTracks(proj)
    local exported_tracks = {}

    -- Deseleccionar todas las pistas primero
    for t = 0, tracks_count - 1 do
        reaper.SetTrackSelected(reaper.GetTrack(proj, t), false)
    end

    local selected_track_count = 0
    for t = 0, tracks_count - 1 do
        local tr = reaper.GetTrack(proj, t)
        local _, track_name = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
        if track_name == "" then
            track_name = "Pista " .. (t + 1)
            reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", track_name, true)
        end

        local is_muted = reaper.GetMediaTrackInfo_Value(tr, "B_MUTE") == 1
        if not is_muted then
            local lower_name = track_name:lower()
            local group = "Otros"
            local is_click = false
            local default_output = 0

            if lower_name:find("click") or lower_name:find("metronomo") or lower_name:find("claqueta") or lower_name:find("cue") or lower_name:find("guia") then
                group = "Click"
                is_click = true
                default_output = 3 -- Out 4 (In-Ear Auriculares)
            elseif lower_name:find("drum") or lower_name:find("bater") or lower_name:find("bajo") or lower_name:find("bass") or lower_name:find("percu") then
                group = "Ritmo"
                default_output = 0 -- Out 1 (FOH L / Main)
            elseif lower_name:find("tecla") or lower_name:find("key") or lower_name:find("piano") or lower_name:find("synth") or lower_name:find("pad") or lower_name:find("organ") then
                group = "Teclados"
                default_output = 1 -- Out 2 (FOH R / Stereo)
            elseif lower_name:find("guit") or lower_name:find("lead") or lower_name:find("acust") or lower_name:find("electr") then
                group = "Guitarras"
                default_output = 2 -- Out 3 (Monitor Guitarras)
            elseif lower_name:find("voz") or lower_name:find("vocal") or lower_name:find("coro") then
                group = "Voces"
                default_output = 1 -- Out 2
            end

            local wav_name = SanitizeFilename(track_name) .. ".wav"

            reaper.SetTrackSelected(tr, true)
            selected_track_count = selected_track_count + 1

            table.insert(exported_tracks, {
                id = "trk-" .. (t + 1),
                name = track_name,
                filename = wav_name,
                volume = 1.0,
                pan = 0.0,
                output_channel = default_output,
                extra_outputs = {},
                aux_volume = 1.0,
                mute = false,
                solo = false,
                is_click = is_click,
                group = group
            })
            Msg(string.format("  + Pista: %-25s -> %-20s [Salida: OUT %d | Grupo: %s]", track_name, wav_name, default_output + 1, group))
        end
    end

    -- Configurar parámetros de renderizado nativo de REAPER
    reaper.GetSetProjectInfo_String(proj, "RENDER_FILE", staging_folder, true)
    reaper.GetSetProjectInfo_String(proj, "RENDER_PATTERN", "$track", true)
    reaper.GetSetProjectInfo(proj, "RENDER_SETTINGS", 3, true)    -- 3 = Selected tracks (stems)
    reaper.GetSetProjectInfo(proj, "RENDER_BOUNDSFLAG", 1, true)  -- 1 = Entire project
    reaper.GetSetProjectInfo(proj, "RENDER_SRATE", 48000, true)   -- 48,000 Hz
    reaper.GetSetProjectInfo(proj, "RENDER_CHANNELS", 1, true)    -- Mono stems (Matriz BSplayer)

    if render_mode == 1 then
        Msg("\n  -> Renderizando " .. selected_track_count .. " stems automáticamente en silencio...")
        -- 42230: Render project, using most recent render settings, silently
        reaper.Main_OnCommand(42230, 0)
    else
        Msg("\n  -> Abriendo ventana de Render de REAPER...")
        Msg("     (Haz clic en 'Render " .. selected_track_count .. " files' y el script esperará a que termine)")
        -- 40015: File: Render project to disk...
        reaper.Main_OnCommand(40015, 0)
    end

    -- Función que empaqueta todo una vez que el renderizado de REAPER está 100% completado
    local function FinishPackaging(rendered_wavs)
        Msg("\n[Renderizado Finalizado al 100%]")
        Msg("  -> Archivos WAV verificados en disco: " .. #rendered_wavs)

        -- Asociar nombres reales de archivos renderizados
        for i, trk in ipairs(exported_tracks) do
            local found_fn = nil
            local clean_trk = trk.name:lower():gsub('[^%w]', '')
            for _, rfn in ipairs(rendered_wavs) do
                local clean_rfn = rfn:lower():gsub('[^%w]', '')
                if clean_rfn == clean_trk or clean_rfn:find(clean_trk) or clean_trk:find(clean_rfn) then
                    found_fn = rfn
                    break
                end
            end
            if not found_fn and rendered_wavs[i] then
                found_fn = rendered_wavs[i]
            end
            if found_fn then
                trk.filename = found_fn
                Msg("     * Pista '" .. trk.name .. "' asociada a: " .. found_fn)
            end
        end

        -- Generar descriptor project.json
        Msg("\n[6/6] Generando descriptor project.json...")
        local json_file_path = staging_folder .. "\\project.json"
        local file = io.open(json_file_path, "w")
        if not file then
            reaper.MB("No se pudo escribir project.json en la carpeta temporal.", "Error", 0)
            return
        end

        file:write("{\n")
        file:write('  "id": "' .. EscapeJSON(song_id) .. '",\n')
        file:write('  "title": "' .. EscapeJSON(song_title) .. '",\n')
        file:write('  "artist": "' .. EscapeJSON(artist_name) .. '",\n')
        file:write('  "bpm": ' .. string.format("%.1f", bpm) .. ',\n')
        file:write('  "time_signature": "4/4",\n')
        file:write('  "duration_seconds": ' .. string.format("%.2f", proj_len) .. ',\n')
        if video_filename then
            file:write('  "video_file": "' .. EscapeJSON(video_filename) .. '",\n')
        else
            file:write('  "video_file": null,\n')
        end
        file:write('  "midi_file": null,\n')

        -- Tracks
        file:write('  "tracks": [\n')
        for i, trk in ipairs(exported_tracks) do
            file:write('    {\n')
            file:write('      "id": "' .. trk.id .. '",\n')
            file:write('      "name": "' .. EscapeJSON(trk.name) .. '",\n')
            file:write('      "filename": "' .. trk.filename .. '",\n')
            file:write('      "volume": ' .. trk.volume .. ',\n')
            file:write('      "pan": ' .. trk.pan .. ',\n')
            file:write('      "output_channel": ' .. trk.output_channel .. ',\n')
            file:write('      "extra_outputs": [],\n')
            file:write('      "aux_volume": ' .. trk.aux_volume .. ',\n')
            file:write('      "mute": false,\n')
            file:write('      "solo": false,\n')
            file:write('      "is_click": ' .. tostring(trk.is_click) .. ',\n')
            file:write('      "group": "' .. trk.group .. '"\n')
            file:write('    }' .. (i < #exported_tracks and ',' or '') .. '\n')
        end
        file:write('  ],\n')

        -- Markers
        file:write('  "markers": [\n')
        for i, m in ipairs(markers) do
            file:write('    {\n')
            file:write('      "name": "' .. EscapeJSON(m.name) .. '",\n')
            file:write('      "time_seconds": ' .. string.format("%.3f", m.time_seconds) .. '\n')
            file:write('    }' .. (i < #markers and ',' or '') .. '\n')
        end
        file:write('  ],\n')

        -- Lyrics
        file:write('  "lyrics": [\n')
        for i, l in ipairs(lyrics) do
            file:write('    {\n')
            file:write('      "time_seconds": ' .. string.format("%.3f", l.time_seconds) .. ',\n')
            file:write('      "text": "' .. EscapeJSON(l.text) .. '",\n')
            if l.chords then
                file:write('      "chords": "' .. EscapeJSON(l.chords) .. '"\n')
            else
                file:write('      "chords": null\n')
            end
            file:write('    }' .. (i < #lyrics and ',' or '') .. '\n')
        end
        file:write('  ],\n')

        -- MIDI Cues
        file:write('  "midi_cues": [\n')
        for i, c in ipairs(midi_cues) do
            file:write('    {\n')
            file:write('      "time_seconds": ' .. string.format("%.3f", c.time_seconds) .. ',\n')
            file:write('      "channel": ' .. (c.channel or 1) .. ',\n')
            file:write('      "type": "' .. c.type .. '",\n')
            if c.type == "program_change" then
                file:write('      "value": ' .. (c.value or 0) .. ',\n')
            elseif c.type == "control_change" then
                file:write('      "cc": ' .. (c.cc or 0) .. ',\n')
                file:write('      "value": ' .. (c.value or 0) .. ',\n')
            elseif c.type == "note_on" then
                file:write('      "note": ' .. (c.note or 60) .. ',\n')
                file:write('      "velocity": ' .. (c.velocity or 127) .. ',\n')
            end
            file:write('      "comment": "' .. EscapeJSON(c.comment or "") .. '"\n')
            file:write('    }' .. (i < #midi_cues and ',' or '') .. '\n')
        end
        file:write('  ]\n')

        file:write("}\n")
        file:close()
        Msg("  -> project.json escrito correctamente.")

        -- Empaquetar todo en el contenedor .bsp único
        Msg("\n==================================================================")
        Msg("   EMPAQUETANDO ARCHIVO ÚNICO .BSP (BSplayer Package)...")
        Msg("==================================================================")

        local python_tool = "D:\\Blas\\BSplayer\\tools\\package_bsp.py"
        local pack_cmd = 'python "' .. python_tool .. '" "' .. staging_folder .. '" -o "' .. final_bsp_file .. '" --remove-source'

        os.execute(pack_cmd)

        local bsp_exists = false
        local test_f = io.open(final_bsp_file, "r")
        if test_f then
            test_f:close()
            bsp_exists = true
        end

        -- Fallback nativo mediante .NET ZipFile (sin errores de extensión o corrupción)
        if not bsp_exists then
            Msg("  -> Empaquetando mediante .NET ZipFile...")
            local net_cmd = 'powershell -NoProfile -Command "Add-Type -AssemblyName \'System.IO.Compression.FileSystem\'; if (Test-Path \'' .. final_bsp_file .. '\') { Remove-Item -Force \'' .. final_bsp_file .. '\' }; [System.IO.Compression.ZipFile]::CreateFromDirectory(\'' .. staging_folder .. '\', \'' .. final_bsp_file .. '\', [System.IO.Compression.CompressionLevel]::Optimal, $false); Remove-Item -Recurse -Force \'' .. staging_folder .. '\'"'
            os.execute(net_cmd)

            test_f = io.open(final_bsp_file, "r")
            if test_f then
                test_f:close()
                bsp_exists = true
            end
        end

        if bsp_exists then
            Msg("\n==================================================================")
            Msg("   ¡EXPORTACIÓN COMPLETADA CON ÉXITO!")
            Msg("   Paquete Único: " .. final_bsp_file)
            Msg("   - Audio Stems:   " .. #exported_tracks)
            Msg("   - Secciones:     " .. #markers)
            Msg("   - Letras/Líneas: " .. #lyrics)
            Msg("   - Cues MIDI:     " .. #midi_cues)
            if video_filename then
                Msg("   - Video Sync:    " .. video_filename)
            end
            Msg("   BSplayer detectará este archivo automáticamente.")
            Msg("==================================================================")

            reaper.MB(
                "¡Canción exportada y empaquetada con éxito!\n\n" ..
                "Archivo único generado:\n" .. final_bsp_file .. "\n\n" ..
                "Incluye: " .. #exported_tracks .. " pistas de audio (48kHz/24b), Marcadores, Letras, Video y Cues MIDI.\n\n" ..
                "BSplayer ya lo tiene listo para reproducir en tu pantalla de 4\" o consola web.",
                "BSplayer Exportador",
                0
            )
        else
            Msg("\n[!] No se pudo generar automáticamente el paquete .bsp.")
            Msg("    Los archivos se encuentran en: " .. staging_folder)
            reaper.MB("Los stems se generaron correctamente en:\n" .. staging_folder .. "\n\nPuedes empaquetarlo ejecutando:\npython tools/package_bsp.py \"" .. staging_folder .. "\"", "Atención", 0)
        end
    end

    -- Bucle asíncrono reaper.defer para esperar a que REAPER termine el renderizado
    local start_time = reaper.time_precise()
    local stable_ticks = 0
    local last_count = 0

    local function PollRenderStatus()
        local current_wavs = {}
        local f_idx = 0
        while true do
            local fn = reaper.EnumerateFiles(staging_folder, f_idx)
            if not fn then break end
            if fn:lower():match("%.wav$") then
                table.insert(current_wavs, fn)
            end
            f_idx = f_idx + 1
        end

        -- Mostrar progreso en consola si se detectan nuevos archivos
        if #current_wavs ~= last_count then
            Msg(string.format("  -> Procesando stems: %d de %d detectados...", #current_wavs, selected_track_count))
            last_count = #current_wavs
        end

        if #current_wavs >= selected_track_count and selected_track_count > 0 then
            local all_closed = true
            for _, fn in ipairs(current_wavs) do
                local full_path = staging_folder .. "\\" .. fn
                local f = io.open(full_path, "r+b")
                if not f then
                    all_closed = false
                    break
                else
                    f:close()
                end
            end

            if all_closed then
                stable_ticks = stable_ticks + 1
                if stable_ticks >= 3 then
                    -- Todos los archivos están completamente renderizados y cerrados por REAPER
                    FinishPackaging(current_wavs)
                    return
                end
            else
                stable_ticks = 0
            end
        end

        -- Tiempo límite de seguridad (10 minutos)
        if reaper.time_precise() - start_time > 600 then
            reaper.MB("El renderizado excedió el tiempo límite (10 min). Revisa la carpeta temporal:\n" .. staging_folder, "Error", 0)
            return
        end

        reaper.defer(PollRenderStatus)
    end

    Msg("\n  -> Esperando finalización del renderizado de REAPER...")
    reaper.defer(PollRenderStatus)
end

Main()
