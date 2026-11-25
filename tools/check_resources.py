"""Bounded launcher caching and media-session teardown without native shortcuts."""
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timedelta,timezone
import sys,os,tempfile
from unittest.mock import patch
install=Path(sys.argv[1]).resolve();root=install/'config/dynamic-island'
sys.path[:0]=[str(root),str(root/'runtime')]
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication,QWidget
from launcher_windows import Catalog
from media import MediaWorker,PlaybackStatus,MediaState
app=QApplication([])
catalog=Catalog(root)
for index in range(200):catalog._received(str(index),QImage(128,128,QImage.Format.Format_ARGB32))
assert len(catalog.images)==Catalog.ICON_CACHE_LIMIT
assert '0' not in catalog.images and '199' in catalog.images
oldest=next(iter(catalog.images))
catalog.request_icons([SimpleNamespace(kind='app',key=oldest,value='unused')])
catalog._received('new',QImage(128,128,QImage.Format.Format_ARGB32))
assert oldest in catalog.images and len(catalog.images)==Catalog.ICON_CACHE_LIMIT
for index in range(200,400):catalog._received(str(index),QImage(128,128,QImage.Format.Format_ARGB32))
assert oldest in catalog.images and len(catalog.images)==Catalog.ICON_CACHE_LIMIT,'Queued stale icons must not evict visible results'
catalog.stop()
controls=SimpleNamespace(is_previous_enabled=True,is_play_pause_toggle_enabled=True,is_pause_enabled=True,is_play_enabled=True,
                         is_next_enabled=True,is_playback_position_enabled=True,is_shuffle_enabled=False,is_repeat_enabled=False)
info=SimpleNamespace(controls=controls,playback_status=PlaybackStatus.PLAYING,playback_rate=1.)
session=SimpleNamespace(get_playback_info=lambda:info,get_timeline_properties=lambda:None,source_app_user_model_id='test')
worker=SimpleNamespace(generation=1,_source_name=lambda _: 'Test player')
snapshot=MediaWorker._snapshot(worker,session,'Track','Artist',b'','Album')
assert snapshot.playing and snapshot.toggle and snapshot.next and snapshot.title=='Track'
assert not snapshot.seek and snapshot.duration==0
timeline=SimpleNamespace(start_time=timedelta(seconds=2),end_time=timedelta(seconds=122),position=timedelta(seconds=32),last_updated_time=None)
session.get_timeline_properties=lambda:timeline
snapshot=MediaWorker._snapshot(worker,session,'Track','Artist',b'','Album')
assert snapshot.duration==120 and snapshot.position==30 and snapshot.seek
info.controls=None
assert MediaWorker._snapshot(worker,session,'Track','Artist',b'','Album')==MediaState()
from liquid_glass import MaterialLayer
class Native:
    def lg_create_wgc(self,*_):return 1
    def lg_light(self,*_):pass
    def lg_destroy(self,*_):pass
    def lg_shutdown(self):pass
with tempfile.TemporaryDirectory(prefix='caelestia-hidden-material-') as directory:
    owner=QWidget();layer=MaterialLayer(directory,owner);layer.lib=Native()
    with patch.object(layer,'_load'):layer.prepare()
    assert layer.context and not layer.timer.isActive(),'Hidden startup must not poll material at 60 Hz'
    layer.timer.start();layer._health();assert not layer.timer.isActive()
    layer.timer.start();layer.hide();assert not layer.timer.isActive()
    layer.close();owner.close()
print('PASS: bounded icon cache, recent-icon retention, media teardown/timeline, valid transport and hidden-material polling.')
