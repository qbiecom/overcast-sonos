import os
import logging
import uuid
from overcast import Overcast, utilities
from pysimplesoap.server import SoapDispatcher, SOAPHandler
from http.server import HTTPServer

logging.basicConfig(level=logging.INFO)
#logging.basicConfig(level=logging.DEBUG)

log = logging.getLogger('overcast-sonos')

DEFAULT_ALBUM_ART_URI = 'http://is3.mzstatic.com/image/thumb/Purple111/v4/20/5b/5e/205b5ef7-ee0e-7d0c-2d11-12f611c579f4/source/175x175bb.jpg'
ALL_PODCASTS_ID = 'all_podcasts'
UNPLAYED_PODCASTS_ID = 'unplayed_podcasts'
UNPLAYED_PODCAST_ID_PREFIX = 'podcast_unplayed'
PODCAST_ID_PREFIX = 'podcast'
REPORT_PLAY_SECONDS_INTERVAL = 30

class customSOAPHandler(SOAPHandler):
    def do_GET(self):
        log.debug('PATH ==> %s', self.path)
        if self.path == '/presentation_map':
            self.send_response(http.HTTPStatus.OK)
            self.send_header('Content-type', 'text/xml')
            self.end_headers()
            self.wfile.write('''<?xml version="1.0" encoding="UTF-8"?>
            <Presentation>
                <PresentationMap type="DisplayType">
                    <RootNodeDisplayType>
                        <DisplayMode>LIST</DisplayMode>
                    </RootNodeDisplayType>
                </PresentationMap>
                <PresentationMap type="QuickSkips">
                    <QuickSkip type="episode.podcast" forwardSeconds="45" backwardSeconds="10"/>
                </PresentationMap>
            </Presentation>
            '''.encode("utf-8"))
            log.info('presentation_map has been sent')
            return
        else:
            return SOAPHandler.do_GET(self)


dispatcher = SoapDispatcher('overcast-sonos',
                            location='http://localhost:8140/',
                            namespace='http://www.sonos.com/Services/1.1',
                            trace=True,
                            debug=True
                            )

overcast = Overcast(os.environ['OVERCAST_USERNAME'], os.environ['OVERCAST_PASSWORD'])

mediaCollection = {'id': str,
                   'title': str,
                   'itemType': str,
                   'artistId': str,
                   'artist': str,
                   'albumArtURI': str,
                   'canPlay': bool,
                   'canEnumerate': bool,
                   'canAddToFavorites': bool,
                   'canScroll': bool,
                   'canSkip': bool}

positionInformation = {'id': str,
                       'index': int,  # always 0, "reserved for future use" by Sonos
                       'offsetMillis': int}

trackMetadata = {'artist': str,
                 'albumArtist': str,
                 'albumArtURI': str,
                 'genreId': str,
                 'duration': int,
                 'canResume': bool}

mediaMetadata = {'id': str,
                 'title': str,
                 'mimeType': str,
                 'itemType': str,
                 'trackMetadata': trackMetadata}

# for some reason, certain podcasts report the incorrect mime_type, fix them here manually
def fixed_mimetype_for_episode(episode):
    title = episode['title']
    if 'Group Therapy Radio' in title:
        log.debug('Forcing \'audio/mp4\' for the mime_type.')
        return 'audio/mp4'
    elif 'Monstercat' in title:
        log.debug('Forcing \'audio/mpeg\' for the mime_type.')
        return 'audio/mpeg'
    else:
        log.debug('Leaving \'' + episode['audio_type'] + '\' for the mime_type.')
        return episode['audio_type']

# returns a media collection object for a podcast entry
def create_podcast_media_collection(podcast, unplayed_only=False):
    # the collection id will differ if it's an unplayed podcast
    if unplayed_only:
        id_prefix = UNPLAYED_PODCAST_ID_PREFIX
    else:
        id_prefix = PODCAST_ID_PREFIX

    return {
        'id': f"{id_prefix}/{podcast['id']}",
        'title': podcast['title'],
        'albumArtURI': podcast['albumArtURI'],
        'itemType': 'album',
        'semanticType': 'podcast',
        'canPlay': False,
        'producer': '',
    }

###


def getSessionId(username, password):
    log.debug('at=getSessionId username=%s password=%s', username, password)
    return username


dispatcher.register_function(
    'getSessionId', getSessionId,
    returns={'getSessionIdResult': str},
    args={'username': str, 'password': str}
)

###

# Gets metadata for podcasts and episodes, depending on which id is sent from Sonos
def getMetadata(id, index, count, recursive=False):
    log.debug('at=getMetadata id=%s index=%s count=%s recursive=%s', id, index, count, recursive)

    if id == 'root':
        # the root view will show a 'all podcasts' subcollection, 'unplayed podcasts' subcollection, and any unplayed podcasts individually
        all_unplayed_podcasts = overcast.get_all_podcasts(unplayed_only=True)
        podcasts = all_unplayed_podcasts[index:index + count]
        response = {'getMetadataResult': [{'index': index, 'count': len(podcasts) + 2, 'total': len(all_unplayed_podcasts) + 2}]}

        # add a collection that will list all podcasts
        response['getMetadataResult'].append({'mediaCollection': {
            'id': ALL_PODCASTS_ID,
            'title': 'All Podcasts',
            'itemType': 'collection',
            'canPlay': False,
            'albumArtURI': DEFAULT_ALBUM_ART_URI
        }})

        # add a collection that will list all unplayed podcasts
        response['getMetadataResult'].append({'mediaCollection': {
            'id': UNPLAYED_PODCASTS_ID,
            'title': 'Unplayed Podcasts',
            'itemType': 'collection',
            'canPlay': False,
            'albumArtURI': DEFAULT_ALBUM_ART_URI
        }})

        # add any unplayed podcasts that might exist
        for podcast in podcasts:
            response['getMetadataResult'].append({'mediaCollection': create_podcast_media_collection(podcast, unplayed_only=True)})
    elif id == ALL_PODCASTS_ID or id == UNPLAYED_PODCASTS_ID:
        # this code path will create a collection shows a list of all podcasts or unplayed podcasts
        all_podcasts = overcast.get_all_podcasts(unplayed_only=(id == UNPLAYED_PODCASTS_ID))
        podcasts = all_podcasts[index:index + count]
        response = {'getMetadataResult': [{'index': index, 'count': len(podcasts), 'total': len(all_podcasts)}]}
        for podcast in podcasts:
            response['getMetadataResult'].append({'mediaCollection': create_podcast_media_collection(podcast, unplayed_only=(id == UNPLAYED_PODCASTS_ID))})
    elif id.startswith(PODCAST_ID_PREFIX):
        # this code path will show episodes available for a given podcast
        id_prefix, podcast_id = id.split('/', 1)
        all_episodes = overcast.get_all_podcast_episodes(podcast_id, unplayed_only=(id_prefix == UNPLAYED_PODCAST_ID_PREFIX))
        episodes = all_episodes[index:index+count]
        response = {'getMetadataResult': [{'index': index, 'count': len(episodes), 'total': len(all_episodes)}]}
        for episode in episodes:
            response['getMetadataResult'].append({
                'mediaMetadata': {
                    'id': 'episodes/' + episode['id'],
                    'title': episode['title'],
                    'mimeType': fixed_mimetype_for_episode(episode),
                    'itemType': 'track',
                    'semanticType': 'episode.podcast',
                    'summary': episode['summary'],
                    'releasedate': episode['releasedate'],
                    'trackMetadata': {
                        'artist': episode['podcast_title'],
                        'albumArtist': episode['podcast_title'],
                        'albumArtURI': episode['albumArtURI'],
                        'genreId': 'podcast',
                        'canResume': True,
                    }
                }
            })
    else:
        logging.error('unknown getMetadata id id=%s', id)
        response = {'getMetadataResult': [{'index': 0, 'count': 0, 'total': 0}]}

    log.debug('at=getMetadata response=%s', response)
    return response


dispatcher.register_function(
    'getMetadata', getMetadata,
    returns={'getMetadataResult': {'index': int, 'count': int, 'total': int, 'mediaCollection': mediaCollection}},
    args={'id': str, 'index': int, 'count': int, 'recursive': bool}
)

###

# Get the metadata for a single item/episode
def getMediaMetadata(id):
    log.debug('at=getMediaMetadata id=%s', id)
    _, episode_id = id.rsplit('/', 1)
    log.debug('at=getMediaMetadata episode_id=%s', episode_id)
    episode = overcast.get_episode_detail(episode_id)
    if episode is not None:
    	response = {'getMediaMetadataResult': {
            'mediaMetadata': {
            'id': id,
            'title': episode['title'],
            'mimeType': fixed_mimetype_for_episode(episode),
            'itemType': 'track',
            'trackMetadata': {
                'artist': episode['podcast_title'],
                'albumArtist': episode['podcast_title'],
                'albumArtURI': episode['albumArtURI'],
                'genreId': 'podcast',
                'duration': episode['duration'],
                'canResume': True,
            }}
    	}}
    	log.debug('at=getMediaMetadata response=%s', response)
    	return response
    else:
        return None


dispatcher.register_function(
    'getMediaMetadata', getMediaMetadata,
    returns={'getMediaMetadataResult': mediaMetadata},
    args={'id': str}
)

###

# Get the URI for an episode
def getMediaURI(id):
    log.debug('at=getMediaURI id=%s', id)
    _, episode_id = id.rsplit('/', 1)
    episode = overcast.get_episode_detail(episode_id)
    parsed_audio_uri = episode['parsed_audio_uri']
    audio_uri = utilities.final_redirect_url(parsed_audio_uri)
    response = {'getMediaURIResult': audio_uri,
                'positionInformation': {
                        'id': 'episodes/' + episode['id'],
                        'index': 0,
                        'offsetMillis': episode['offsetMillis']
                    },
                }
    log.debug('at=getMediaURI response=%s', response)
    return response


dispatcher.register_function(
    'getMediaURI', getMediaURI,
    returns={'getMediaURIResult': str, 'positionInformation': positionInformation},
    args={'id': str}
)

###


def getLastUpdate():
    log.debug('at=getLastUpdate')
    return {'getLastUpdateResult': {'catalog': str(uuid.uuid4()), 'favorites': '0', 'pollInterval': 60}}


dispatcher.register_function(
    'getLastUpdate', getLastUpdate,
    returns={'getLastUpdateResult': {'autoRefreshEnabled': bool, 'catalog': str, 'favorites': str, 'pollInterval': int}},
    args={}
)

###


def reportPlaySeconds(id, seconds, offsetMillis, contextId):
    episode_id = id.rsplit('/', 1)[-1]
    log.debug('at=reportPlaySeconds and id=%s, seconds=%d, offsetMillis=%d, contextId=%s, episode_id=%s', id, seconds, offsetMillis, contextId, episode_id)
    episode = overcast.get_episode_detail(episode_id, offsetMillis)
    overcast.update_episode_offset(episode, offsetMillis/1000)
    return {'reportPlaySecondsResult': {'interval': REPORT_PLAY_SECONDS_INTERVAL}}


dispatcher.register_function(
    'reportPlaySeconds', reportPlaySeconds,
    returns={'reportPlaySecondsResult': {'interval': int}},
    args={'id': str, 'seconds': int, 'offsetMillis': int, 'contextId': str}
)


def reportPlayStatus(id, status, offsetMillis, contextId):
    episode_id = id.rsplit('/', 1)[-1]
    log.debug('at=reportPlayStatus and id=%s, status=%s, contextId=%s, offsetMillis=%d, episode_id=%s', id, status, contextId, offsetMillis, episode_id)
    episode = overcast.get_episode_detail(episode_id, offsetMillis)
    overcast.update_episode_offset(episode, offsetMillis/1000)


dispatcher.register_function(
    'reportPlayStatus', reportPlayStatus,
    returns={},
    args={'id': str, 'status': str, 'offsetMillis': int, 'contextId': str}
)


def setPlayedSeconds(id, seconds, offsetMillis, contextId):
    episode_id = id.rsplit('/', 1)[-1]
    log.debug('at=setPlayedSeconds and id=%s, seconds=%d, offsetMillis=%d, contextId=%s, episode_id=%s', id, seconds, offsetMillis, contextId, episode_id)
    episode = overcast.get_episode_detail(episode_id, offsetMillis)
    overcast.update_episode_offset(episode, offsetMillis/1000)


dispatcher.register_function(
    'setPlayedSeconds', setPlayedSeconds,
    returns={},
    args={'id': str, 'seconds': int, 'offsetMillis': int, 'contextId': str}
)


if __name__ == '__main__':
    log.info('at=start')
    httpd = HTTPServer(("", 8140), customSOAPHandler)
    httpd.dispatcher = dispatcher
    httpd.serve_forever()
