# -*- coding: utf-8 -*-
'''
    The Unofficial KissAnime Plugin - a plugin for Kodi
    Copyright (C) 2016  dat1guy

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''


import os, xbmcvfs
from metahandler.metahandlers import MetaData
from metahandler.TMDB import TMDB
from metahandler.thetvdbapi import TheTVDB
from metahandler import common
from resources.lib.common.helpers import helper


def make_dir(mypath, dirname):
    ''' Creates sub-directories if they are not found. '''
    subpath = os.path.join(mypath, dirname)
    try:
        if not xbmcvfs.exists(subpath): xbmcvfs.mkdirs(subpath)
    except:
        if not os.path.exists(subpath): os.makedirs(subpath)              
    return subpath

def bool2string(myinput):
    ''' Neatens up usage of prepack_images flag. '''
    if myinput is False: return 'false'
    elif myinput is True: return 'true'

'''
   Use SQLIte3 wherever possible, needed for newer versions of XBMC
   Keep pysqlite2 for legacy support
'''
try:
    if  common.addon.get_setting('use_remote_db')=='true' and   \
        common.addon.get_setting('db_address') is not None and  \
        common.addon.get_setting('db_user') is not None and     \
        common.addon.get_setting('db_pass') is not None and     \
        common.addon.get_setting('db_name') is not None:
        import mysql.connector as database
        common.addon.log('Loading MySQLdb as DB engine version: %s' % database.version.VERSION_TEXT, 2)
        DB = 'mysql'
    else:
        raise ValueError('MySQL not enabled or not setup correctly')
except:
    try: 
        from sqlite3 import dbapi2 as database
        common.addon.log('Loading sqlite3 as DB engine version: %s' % database.sqlite_version, 2)
    except: 
        from pysqlite2 import dbapi2 as database
        common.addon.log('pysqlite2 as DB engine', 2)
    DB = 'sqlite'


class LooseMetaData(MetaData):
    def __init__(self, prepack_images=False, preparezip=False, tmdb_api_key='af95ef8a4fe1e697f86b8c194f2e5e11'):
        '''
        A copy of __init__ from the metahandler plugin, modified to use a 
        different db path, which unfortunately required pasting this function 
        and modifying it :/
        '''
        #Check if a path has been set in the addon settings
        settings_path = common.addon.get_setting('meta_folder_location')
        
        # TMDB constants
        self.tmdb_image_url = ''
        self.tmdb_api_key = tmdb_api_key

        self.path = helper.get_profile()
        self.cache_path = make_dir(self.path, 'meta_cache')

        if prepack_images:
            #create container working directory
            #!!!!!Must be matched to workdir in metacontainers.py create_container()
            self.work_path = make_dir(self.path, 'work')
            
        #set movie/tvshow constants
        self.type_movie = 'movie'
        self.type_tvshow = 'tvshow'
        self.type_season = 'season'        
        self.type_episode = 'episode'
            
        #this init auto-constructs necessary folder hierarchies.

        # control whether class is being used to prepare pre-packaged .zip
        self.prepack_images = bool2string(prepack_images)
        self.videocache = os.path.join(self.cache_path, 'video_cache.db')
        self.tvpath = make_dir(self.cache_path, self.type_tvshow)
        self.tvcovers = make_dir(self.tvpath, 'covers')
        self.tvbackdrops = make_dir(self.tvpath, 'backdrops')
        self.tvbanners = make_dir(self.tvpath, 'banners')
        self.mvpath = make_dir(self.cache_path, self.type_movie)
        self.mvcovers = make_dir(self.mvpath, 'covers')
        self.mvbackdrops = make_dir(self.mvpath, 'backdrops')

        # connect to db at class init and use it globally
        if DB == 'mysql':
            class MySQLCursorDict(database.cursor.MySQLCursor):
                def _row_to_python(self, rowdata, desc=None):
                    row = super(MySQLCursorDict, self)._row_to_python(rowdata, desc)
                    if row:
                        return dict(zip(self.column_names, row))
                    return None
            db_address = common.addon.get_setting('db_address')
            db_port = common.addon.get_setting('db_port')
            if db_port: db_address = '%s:%s' %(db_address,db_port)
            db_user = common.addon.get_setting('db_user')
            db_pass = common.addon.get_setting('db_pass')
            db_name = common.addon.get_setting('db_name')
            self.dbcon = database.connect(database=db_name, user=db_user, password=db_pass, host=db_address, buffered=True)
            self.dbcur = self.dbcon.cursor(cursor_class=MySQLCursorDict, buffered=True)
        else:
            self.dbcon = database.connect(self.videocache)
            self.dbcon.row_factory = database.Row # return results indexed by field names and not numbers so we can convert to dict
            self.dbcur = self.dbcon.cursor()

        # initialize cache db
        self._cache_create_movie_db()
        
        # Check TMDB configuration, update if necessary
        self._set_tmdb_config()

        # Add the absolute_number column here, which is helpful for animes
        if not self._does_column_exist('absolute_episode', 'episode_meta'):
            sql_alter = "ALTER TABLE episode_meta ADD absolute_episode INTEGER"
            try:
                self.dbcur.execute(sql_alter)
                helper.log_debug('Successfully added the absolute_episode column')
            except:
                helper.log_debug('Failed to alter the table')
        else:
            helper.log_debug('The absolute_episode column already exists')

    def _does_column_exist(self, column_name, table):
        sql_pragma = 'PRAGMA table_info(episode_meta)'
        try:
            self.dbcur.execute(sql_pragma)
            matched_rows = self.dbcur.fetchall()
        except:
            common.addon.log_debug('Unable to execute sql for column existance query')
            return True
        return ([r for r in matched_rows if r['name'] == 'absolute_episode'] != [])

    def _MetaData__init_episode_meta(self, imdb_id, tvdb_id, episode_title, season, episode, air_date):
        meta = MetaData._MetaData__init_episode_meta(self, imdb_id, tvdb_id, episode_title, season, episode, air_date)
        meta['absolute_episode'] = 0
        return meta
    
    def get_episodes_meta(self, tvshowtitle, imdb_id, first_air_date, num_episodes):
        '''
        Returns all metadata about the given number of episodes (inclusive) for
        the given show, starting at the given first air date.
        '''
        helper.start('get_episodes_meta')
        if imdb_id:
            imdb_id = self._valid_imdb_id(imdb_id)

        tvdb_id = self._get_tvdb_id(tvshowtitle, imdb_id)

        # Look up in cache first
        meta_list = self._cache_lookup_episodes(imdb_id, tvdb_id, first_air_date, num_episodes)

        if not meta_list:
            if tvdb_id:
                # if not cached, grab all of the raw data using get_show_and_episodes()
                helper.log_debug('Grabbing show and episodes for metadata')
                tvdb = TheTVDB(language=self._MetaData__get_tvdb_language())
                (show, episode_list) = tvdb.get_show_and_episodes(tvdb_id)
                meta_list = [self.episode_to_meta(ep, tvshowtitle, show) for ep in episode_list]
                # we want to save the metadata for all the episodes (for 
                # caching reasons), so we'll filter later
            else:
                helper.log_debug('No TVDB ID available, could not find TV show with imdb: %s' % imdb_id)
                tvdb_id = ''

            if not meta_list:
                meta_list = [self._MetaData__init_episode_meta(imdb_id, tvdb_id, '', 0, 0, first_air_date)]
                meta_list[0]['playcount'] = 0
                meta_list[0]['TVShowTitle'] = tvshowtitle

            self._cache_save_episodes_meta(meta_list)

            # filter out those that start before first_air_date (and have no 
            # absolute number) and those that come after + num_episdoes
            tmp_meta_list = []
            for meta in meta_list:
                if num_episodes == 0: # end of the sequence
                    break
                if meta['absolute_episode'] == -1:
                    helper.log_debug('Filtering out meta %s' % str(meta))
                    continue
                if len(tmp_meta_list) > 0: # middle of the sequence
                    helper.log_debug('Found next meta %s' % str(meta))
                    tmp_meta_list.append(meta)
                    num_episodes -= 1
                elif meta['premiered'] == first_air_date: # start of the sequence
                    helper.log_debug('Found first meta %s' % str(meta))
                    tmp_meta_list.append(meta)
                    num_episodes -= 1
                else:
                    helper.log_debug('Skipping meta %s' % str(meta))
            meta_list = tmp_meta_list

        helper.end('get_episodes_meta')
        return meta_list

    def _cache_lookup_episodes(self, imdb_id, tvdb_id, first_air_date, num_episodes):
        '''
        Lookup metadata for multiple episodes starting from the first air date
        for the given number of episodes.
        '''
        return []

    def _cache_save_episodes_meta(self, meta_list):
        '''
        Save metadata of multiple episodes to local cache db.
        '''

        return

    def _get_tvdb_meta(self, imdb_id, name, year=''):
        '''
        Requests meta data from TVDB and creates proper dict to send back.
        This version is a bit looser in determining if we can use the given 
        results, and also checks against aliases.
        
        Args:
            imdb_id (str): IMDB ID
            name (str): full name of movie you are searching
        Kwargs:
            year (str): 4 digit year of movie, when imdb_id is not available it is recommended
                        to include the year whenever possible to maximize correct search results.
                        
        Returns:
            DICT. It must also return an empty dict when
            no movie meta info was found from tvdb because we should cache
            these "None found" entries otherwise we hit tvdb alot.
        '''      
        common.addon.log('Starting TVDB Lookup', 0)
        helper.start('_get_tvdb_meta')
        tvdb = TheTVDB(language=self._MetaData__get_tvdb_language())
        tvdb_id = ''
                
        try:
            if imdb_id:
                tvdb_id = tvdb.get_show_by_imdb(imdb_id)
        except Exception, e:
            common.addon.log('************* Error retreiving from thetvdb.com: %s ' % e, 4)
            tvdb_id = ''
            pass
            
        #Intialize tvshow meta dictionary
        meta = self._init_tvshow_meta(imdb_id, tvdb_id, name, year)

        # if not found by imdb, try by name
        if tvdb_id == '':
            try:
                #If year is passed in, add it to the name for better TVDB search results
                if year:
                    name = name + ' ' + year
                show_list = tvdb.get_matching_shows(name, want_raw=True)
            except Exception, e:
                common.addon.log('************* Error retreiving from thetvdb.com: %s ' % e, 4)
                show_list = []
                pass
            common.addon.log('Found TV Show List: %s' % show_list, 0)
            tvdb_id=''
            prob_id=''

            helper.log_debug('Here are the raw results: %s' % str(show_list))
            strcmp = self._string_compare
            clean = self._clean_string
            for show in show_list:
                # this is probably our result
                tmp_imdb_id = show['IMDB_ID'] if show.has_key('IMDB_ID') else None
                if tmp_imdb_id == imdb_id or strcmp(clean(show['SeriesName']), clean(name)) or len(show_list) == 1: # if the list length is one, then this is probably the right result
                    tvdb_id = clean(show['seriesid'])
                    if not imdb_id:
                        imdb_id = clean(tmp_imdb_id)
                    break
                # Check aliases
                if show.has_key('AliasNames'):
                    helper.log_debug('looking at AliasNames: ' + show['AliasNames'].encode('ascii', errors='xmlcharrefreplace'))
                    helper.log_debug('here it is split: %s' % str(show['AliasNames'].encode('ascii', errors='xmlcharrefreplace').split('|')))
                    for alias in show['AliasNames'].split('|'):
                        if strcmp(clean(alias), clean(name)):
                            prob_id = clean(show['seriesid'])
                            if not imdb_id:
                                imdb_id = clean(tmp_imdb_id)
            if tvdb_id == '' and prob_id != '':
                tvdb_id = self._clean_string(prob_id)

        if tvdb_id:
            common.addon.log('Show *** ' + name + ' *** found in TVdb. Getting details...', 0)

            try:
                show = tvdb.get_show(tvdb_id)
            except Exception, e:
                common.addon.log('************* Error retreiving from thetvdb.com: %s ' % e, 4)
                show = None
                pass
            
            if show is not None:
                meta['imdb_id'] = imdb_id
                meta['tvdb_id'] = tvdb_id
                meta['title'] = name
                if str(show.rating) != '' and show.rating != None:
                    meta['rating'] = float(show.rating)
                meta['duration'] = int(show.runtime) * 60
                meta['plot'] = show.overview
                meta['mpaa'] = show.content_rating
                meta['premiered'] = str(show.first_aired)

                #Do whatever we can to set a year, if we don't have one lets try to strip it from show.first_aired/premiered
                if not year and show.first_aired:
                        #meta['year'] = int(self._convert_date(meta['premiered'], '%Y-%m-%d', '%Y'))
                        meta['year'] = int(meta['premiered'][:4])

                if show.genre != '':
                    temp = show.genre.replace("|",",")
                    temp = temp[1:(len(temp)-1)]
                    meta['genre'] = temp
                meta['studio'] = show.network
                meta['status'] = show.status
                if show.actors:
                    for actor in show.actors:
                        meta['cast'].append(actor)
                meta['banner_url'] = show.banner_url
                meta['imgs_prepacked'] = self.prepack_images
                meta['cover_url'] = show.poster_url
                meta['backdrop_url'] = show.fanart_url
                meta['overlay'] = 6

                if meta['plot'] == 'None' or meta['plot'] == '' or meta['plot'] == 'TBD' or meta['plot'] == 'No overview found.' or meta['rating'] == 0 or meta['duration'] == 0 or meta['cover_url'] == '':
                    common.addon.log(' Some info missing in TVdb for TVshow *** '+ name + ' ***. Will search imdb for more', 0)
                    helper.log_debug('help me please %s' % str(dir(self)))
                    tmdb = TMDB(api_key=self.tmdb_api_key, lang=self._MetaData__get_tmdb_language())
                    imdb_meta = tmdb.search_imdb(name, imdb_id)
                    if imdb_meta:
                        imdb_meta = tmdb.update_imdb_meta(meta, imdb_meta)
                        if imdb_meta.has_key('overview'):
                            meta['plot'] = imdb_meta['overview']
                        if imdb_meta.has_key('rating'):
                            meta['rating'] = float(imdb_meta['rating'])
                        if imdb_meta.has_key('runtime'):
                            meta['duration'] = int(imdb_meta['runtime']) * 60
                        if imdb_meta.has_key('cast'):
                            meta['cast'] = imdb_meta['cast']
                        if imdb_meta.has_key('cover_url'):
                            meta['cover_url'] = imdb_meta['cover_url']

                return meta
            else:
                tmdb = TMDB(api_key=self.tmdb_api_key, lang=self._MetaData__get_tmdb_language())
                imdb_meta = tmdb.search_imdb(name, imdb_id)
                if imdb_meta:
                    meta = tmdb.update_imdb_meta(meta, imdb_meta)
                return meta    
        else:
            return meta

    def episode_to_meta(self, episode, tvshowtitle, show, overlay=6, playcount=0):
        meta = {}
        meta['imdb_id'] = self._check(episode.imdb_id)
        meta['tvdb_id'] = self._check(episode.show_id)
        meta['episode_id'] = self._check(episode.id)
        meta['season'] =  int(self._check(episode.season_number, 0))
        meta['episode'] = int(self._check(episode.episode_number, 0))
        meta['title'] = self._check(episode.name)
        meta['director'] = self._check(episode.director)
        meta['writer'] = self._check(episode.writer)
        meta['plot'] = self._check(episode.overview)
        if episode.guest_stars:
            guest_stars = episode.guest_stars
            if guest_stars.startswith('|'):
                guest_stars = guest_stars[1:-1]
            guest_stars = guest_stars.replace('|', ', ')
            meta['plot'] = meta['plot'] + '\n\nGuest Starring: ' + guest_stars
        meta['rating'] = float(self._check(episode.rating, 0))
        meta['premiered'] = self._check(episode.first_aired)
        meta['poster'] = self._check(episode.image)
        meta['cover_url'] =  self._check(episode.image)
        meta['trailer_url'] = ''
        meta['overlay'] = overlay
        meta['playcount'] = playcount
        meta['absolute_episode'] = int(self._check(episode.absolute_number)) if episode.absolute_number else -1

        if show.genre != '':
            temp = show.genre.replace("|",",")
            meta['genre'] = temp[1:(len(temp)-1)]
        meta['duration'] = int(show.runtime) * 60
        meta['studio'] = self._check(show.network)
        meta['mpaa'] = show.content_rating
        meta['backdrop_url'] = show.fanart_url
        meta['banner_url'] = show.banner_url

        return meta