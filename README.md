# yt-dl

A local YouTube downloader for personal use. Runs on `localhost`, downloads one
video at a time, and hands the file to your browser.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- ffmpeg (`sudo apt install ffmpeg`)

## Setup

Débutant ? Deux scripts font tout pour vous :

    ./check.sh      # diagnostic : vérifie ce qui est installé (ne modifie rien)
    ./install.sh    # installe uv, crée l'environnement et les dépendances

Sinon, en une commande :

    uv sync --extra dev

## Run

    ./run.sh

Then open http://127.0.0.1:8000

Set a different port with `PORT=8765 ./run.sh`.

## Use

1. Paste a YouTube URL and click **Probe**.
2. Pick **Video** — quality, container, subtitle tracks — or **Audio** —
   format and bitrate.
3. Click **Download**. Progress streams live, and the file saves through your
   browser when it is ready.

Quality options are drawn as a ladder: each bar's width is that option's
approximate file size, so you can compare sizes at a glance.

Selecting a subtitle track switches the container to MKV, which carries
subtitles as toggleable tracks that MP4 converts to a format many players
ignore. Switch back to MP4 if you need it.

Choosing **Best** under Audio keeps the original stream with no re-encoding, so
the bitrate setting does not apply and is disabled.

## Tests

    uv run pytest              # fast, offline
    uv run pytest -m network   # real downloads

## How it works

`yt-dlp` runs as a Python library on a worker thread, one thread per download.
Job state lives in memory, progress reaches the browser over server-sent
events, and each job downloads into its own temp directory.

Nothing is kept after a download completes: the temp directory is deleted once
the file has been sent, or after 30 minutes if it never was. There is no
history, no database, and no authentication — it is built to run on your own
machine, for your own use.
