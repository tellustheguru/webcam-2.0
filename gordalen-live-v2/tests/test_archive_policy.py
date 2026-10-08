import sys
from unittest.mock import MagicMock,patch
sys.path.insert(0,'/opt/webcam-2.0')
import youtube_live_manager as m
api=MagicMock()
api.channels.return_value.list.return_value.execute.return_value={'items':[{'id':'channel'}]}
api.liveStreams.return_value.list.return_value.execute.return_value={'items':[{'id':'stream','snippet':{'title':'Webcam 2.0'}}]}
def b(id,state,bound,title='Gördalens webbkamera LIVE'):
 return {'id':id,'status':{'lifeCycleStatus':state},'contentDetails':{'boundStreamId':bound},'snippet':{'title':title}}
api.liveBroadcasts.return_value.list.return_value.execute.side_effect=[{'items':[b('live','live','stream')],'nextPageToken':'next'},{'items':[b('archive','complete','stream'),b('other-video','complete','stream','Other'),b('other-stream','complete','another')]}]
with patch.object(m,'_youtube',return_value=api):
 assert m.ensure_youtube_broadcast('channel',logger=lambda _:None)==('live',False)
api.liveBroadcasts.return_value.delete.assert_called_once_with(id='archive')
assert api.liveBroadcasts.return_value.list.call_args_list[1].kwargs['pageToken']=='next'
print('PASS: completed webcam archives deleted before returning existing live; pagination supported; unrelated broadcasts untouched.')
