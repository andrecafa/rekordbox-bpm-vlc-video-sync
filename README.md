# Rekordbox master bpm sync to VLC video frame-rate

Intended to work in conjunction with <https://github.com/Unreal-Dan/RekordBoxSongExporter>[RekordBoxSongExporter]

This script attempts to sync the playback rate and frame-rate of a video playing in VLC to the master_bpm in Rekordbox.

Check out <https://www.silvermansound.com/bpm-to-fps-calculator>[BPM to FPS calculator] for a more detailed explanation of the math used.

## Functions

-- This script monitors a folder for file updates created by the exporter
-- On file update, extracts the metadata out of the GDI text template
-- Interfaces with VLC http control interface to query for current status, playback rate, and video codec frame-rate
-- Computes a value for a framerate that would be a better fit into the current bpm
-- If new rate is significantly different, updates the rate in VLC
-- Runs 2 threads, file monitor and vlc interface, as daemons, until killed

## Configuration

Configure the following variables

-- `WATCH_FOLDER` Path to the folder to monitor set in the Exporter default: "./gdi_files"
-- `VLC_HOST` http interface to VLC, needs to be turned on in Preferances default: "http://localhost:8080"
-- `VLC_PASSWORD` set in VLC > Preferences > All > Interface > Main interfaces > Lua > Password
-- `TEMPLATE_MAP` key value pairs with filename as key and the template as value, set in Exporter. The default includes all the variables current version of Exporter can grab
