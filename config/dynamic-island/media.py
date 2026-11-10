import asyncio
from dataclasses import dataclass
import logging
import threading
import time

from PySide6.QtCore import QObject, Signal
from winrt.windows.media import MediaPlaybackAutoRepeatMode as RepeatMode
from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)
from winrt.windows.storage.streams import Buffer, InputStreamOptions


async def read_image_bytes(reference):
    stream = await reference.open_read_async()
    try:
        if not 0 < stream.size <= 6 * 1024 * 1024:
            return b''
        buffer = Buffer(stream.size)
        return bytes(await stream.read_async(buffer, buffer.capacity, InputStreamOptions.READ_AHEAD))
    finally:
        stream.close()


@dataclass(frozen=True)
class MediaState:
    generation: int = 0
    title: str = ''
    artist: str = ''
    artwork: bytes = b''
    playing: bool = False
    previous: bool = False
    toggle: bool = False
    next: bool = False
    seek: bool = False
    start: float = 0.0
    duration: float = 0.0
    position: float = 0.0
    captured_at: float = 0.0
    rate: float = 1.0
    shuffle: bool | None = None
    repeat: RepeatMode | None = None
    album: str = ''
    source: str = ''

    def elapsed(self):
        age = time.monotonic() - self.captured_at if self.playing else 0.0
        return min(self.duration, max(0.0, self.position + age * self.rate))


class MediaWorker(QObject):
    changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.loop = None
        self.task = None
        self.session = None
        self.generation = 0
        self.resume_session = None
        self.pause_observed = False
        self.wake = None
        self.thread = threading.Thread(target=self._run, daemon=True, name='Windows Media')
        self.thread.start()

    def _run(self):
        asyncio.run(self._serve())

    async def _serve(self):
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        while True:
            try:
                await self._listen(await SessionManager.request_async())
            except asyncio.CancelledError:
                return
            except Exception:
                logging.exception('Windows Media listener will reconnect')
                self.changed.emit(MediaState())
                await asyncio.sleep(5)

    async def _listen(self, manager):
        wake = asyncio.Event()
        self.wake = wake
        refresh_metadata = True

        def notify(metadata):
            nonlocal refresh_metadata
            refresh_metadata |= metadata
            wake.set()

        def callback(metadata):
            def on_event(*_):
                try:
                    self.loop.call_soon_threadsafe(notify, metadata)
                except RuntimeError:
                    pass
            return on_event

        manager_events = self._subscribe(manager, callback, current_session_changed=True, sessions_changed=True)
        session_events = []
        title = artist = album = ''
        artwork = b''
        metadata_retry_at = 0.0
        try:
            while True:
                wake.clear()
                session = self._select_session(manager)
                if session != self.session:
                    self._unsubscribe(session_events)
                    session_events = []
                    self.session = session
                    if session != self.resume_session:
                        self.resume_session = None
                        self.pause_observed = False
                    self.generation += 1
                    title = artist = album = ''
                    artwork = b''
                    refresh_metadata = True
                    if session is not None:
                        session_events = self._subscribe(
                            session, callback, media_properties_changed=True,
                            timeline_properties_changed=False, playback_info_changed=False,
                        )
                if session is not None:
                    if refresh_metadata:
                        refresh_metadata = False
                        metadata_retry_at = time.monotonic() + 4.0
                        try:
                            props = await asyncio.wait_for(session.try_get_media_properties_async(), 1.5)
                            new_title = ' '.join(props.title.split())
                            new_artist = ' '.join(props.artist.split())
                            new_album = ' '.join(props.album_title.split())
                            if (new_title, new_artist, new_album) != (title, artist, album):
                                self.generation += 1
                                title, artist, album, artwork = new_title, new_artist, new_album, b''
                            if props.thumbnail and not artwork:
                                artwork = await asyncio.wait_for(read_image_bytes(props.thumbnail), 0.8)
                        except (OSError, TimeoutError, asyncio.TimeoutError):
                            pass
                    if session != self._select_session(manager):
                        self.changed.emit(MediaState())
                        continue
                    state = self._snapshot(session, title, artist, artwork, album)
                    if session == self.resume_session:
                        if state.playing and self.pause_observed:
                            self._clear_pause()
                        elif state.title and not state.playing:
                            self.pause_observed = True
                    self.changed.emit(state)
                else:
                    self.changed.emit(MediaState())
                try:
                    await asyncio.wait_for(wake.wait(), 1.25)
                except asyncio.TimeoutError:
                    refresh_metadata |= (not title or not artwork) and time.monotonic() >= metadata_retry_at
        finally:
            self._unsubscribe(session_events)
            self._unsubscribe(manager_events)
            self.session = None
            self.resume_session = None
            self.pause_observed = False
            self.wake = None

    def _select_session(self, manager):
        current = manager.get_current_session()
        sessions = tuple(manager.get_sessions())
        for session in (current, self.session, *sessions):
            if session is not None and session in sessions and self._status(session) == PlaybackStatus.PLAYING:
                return session
        if self.resume_session in sessions and self._status(self.resume_session) == PlaybackStatus.PAUSED:
            return self.resume_session
        return None

    @staticmethod
    def _status(session):
        try:
            info = session.get_playback_info()
            return info.playback_status if info else PlaybackStatus.CLOSED
        except OSError:
            return PlaybackStatus.CLOSED

    @staticmethod
    def _subscribe(target, callback, **events):
        return [(getattr(target, 'remove_' + name), getattr(target, 'add_' + name)(callback(metadata)))
                for name, metadata in events.items()]

    @staticmethod
    def _unsubscribe(subscriptions):
        for remove, token in subscriptions:
            try:
                remove(token)
            except OSError:
                pass

    def _snapshot(self, session, title, artist, artwork, album):
        info = session.get_playback_info()
        if not info or not title or info.playback_status not in (PlaybackStatus.PLAYING, PlaybackStatus.PAUSED):
            return MediaState()
        controls = info.controls
        playing = info.playback_status == PlaybackStatus.PLAYING
        rate = info.playback_rate or 1.0
        timeline = session.get_timeline_properties()
        start = timeline.start_time.total_seconds()
        duration = timeline.end_time.total_seconds() - start
        position = timeline.position.total_seconds() - start
        if playing and duration > 0:
            age = time.time() - timeline.last_updated_time.timestamp()
            if 0 < age < 24 * 3600:
                position += age * rate
        return MediaState(
            generation=self.generation, title=title, artist=artist, artwork=artwork, playing=playing,
            previous=controls.is_previous_enabled, toggle=controls.is_play_pause_toggle_enabled or (
                controls.is_pause_enabled if playing else controls.is_play_enabled
            ), next=controls.is_next_enabled, seek=controls.is_playback_position_enabled,
            start=start, duration=max(0.0, duration), position=position, captured_at=time.monotonic(), rate=rate,
            shuffle=bool(info.is_shuffle_active) if controls.is_shuffle_enabled else None,
            repeat=(info.auto_repeat_mode or RepeatMode.NONE) if controls.is_repeat_enabled else None,
            album=album, source=self._source_name(session.source_app_user_model_id),
        )

    @staticmethod
    def _source_name(app_id):
        app_id = app_id.casefold()
        for key, label in (('spotify', 'Spotify'), ('chrome', 'Google Chrome'), ('msedge', 'Microsoft Edge'),
                           ('firefox', 'Firefox'), ('brave', 'Brave'), ('zunemusic', 'Media Player'),
                           ('vlc', 'VLC'), ('musicbee', 'MusicBee'), ('itunes', 'iTunes')):
            if key in app_id:
                return label
        return 'Trình phát Windows'

    def command(self, generation, action, value=0.0):
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._schedule, generation, action, value)

    def _schedule(self, generation, action, value):
        self.loop.create_task(self._command(generation, action, value))

    def release_pause(self):
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._clear_pause)

    def _clear_pause(self):
        self.resume_session = None
        self.pause_observed = False
        if self.wake:
            self.wake.set()

    async def _command(self, generation, action, value):
        session = self.session
        if session is None or generation != self.generation:
            return
        try:
            if action == 'toggle':
                info = session.get_playback_info()
                if not info or info.playback_status not in (PlaybackStatus.PLAYING, PlaybackStatus.PAUSED):
                    return
                playing = info.playback_status == PlaybackStatus.PLAYING
                if playing:
                    self.resume_session = session
                    self.pause_observed = False
                accepted = False
                try:
                    if playing and info.controls.is_pause_enabled:
                        accepted = await session.try_pause_async()
                    elif not playing and info.controls.is_play_enabled:
                        accepted = await session.try_play_async()
                    if not accepted and info.controls.is_play_pause_toggle_enabled:
                        accepted = await session.try_toggle_play_pause_async()
                finally:
                    if self.resume_session == session and playing and not accepted:
                        self._clear_pause()
            elif action == 'previous':
                await session.try_skip_previous_async()
            elif action == 'next':
                await session.try_skip_next_async()
            elif action == 'seek':
                await session.try_change_playback_position_async(round(value * 10_000_000))
            elif action == 'shuffle':
                await session.try_change_shuffle_active_async(bool(value))
            elif action == 'repeat':
                await session.try_change_auto_repeat_mode_async(RepeatMode(value))
        except OSError:
            logging.debug('Media session rejected %s', action, exc_info=True)

    def stop(self):
        if self.task and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.task.cancel)
            self.thread.join(timeout=0.5)
