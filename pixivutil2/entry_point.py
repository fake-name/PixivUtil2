#!/usr/bin/python
# -*- coding: utf-8 -*-
# pylint: disable=I0011, C, C0302, W0602, W0603, W0703, R0102, R1702, R0912, R0915

# pylint: disable=W,R

import codecs
import datetime
import gc
import getpass
import http.client
import mechanize
import os
import random
import re
import subprocess
import sys
import time
import traceback
import urllib.request
import urllib.error
import urllib.parse
from bs4 import BeautifulSoup
from optparse import OptionParser

from .util import datetime_z
from . import PixivBrowserFactory
from . import PixivConfig
from . import PixivConstant
from . import PixivDBManager
from . import PixivHelper
from . import PixivModelFanbox
from .PixivException import PixivException
from .PixivModel import PixivBookmark
from .PixivModel import PixivGroup
from .PixivModel import PixivImage
from .PixivModel import PixivListItem
from .PixivModel import PixivNewIllustBookmark
from .PixivModel import PixivTags


DEBUG_SKIP_PROCESS_IMAGE = False

# gc.enable()
# gc.set_debug(gc.DEBUG_LEAK)

start_iv = False
dfilename = ""

# http://www.pixiv.net/member_illust.php?mode=medium&illust_id=18830248
__re_illust = re.compile(r'member_illust.*illust_id=(\d*)')
__re_manga_page = re.compile(r'(\d+(_big)?_p\d+)')


class PixivUtil():

    def __init__(self):

        self.np_is_valid = False
        self.end_page_num = 0

        self.log = PixivHelper.getLogger()
        self._config = PixivConfig.PixivConfig()
        self._configfile = "config.ini"
        self._db_manager = None
        self._browser = None
        self._blacklist_tags = list()
        self._supress_tags = list()
        self._error_list = list()
        self._last_error_code = 0
        self._blacklist_members = list()
        self._valid_options = tuple()
        self._operation = ''

    # Getter setter block for things that used to be global.
    @property
    def config(self):
        self.log.debug("Getting configfile")
        return self._config

    @config.setter
    def config(self, value):
        self.log.debug("Setting config")
        self._config = value

    @property
    def configfile(self):
        self.log.debug("Getting configfile")
        return self._configfile

    @configfile.setter
    def configfile(self, value):
        self.log.debug("Setting configfile")
        self._configfile = value

    @property
    def db_manager(self):
        self.log.debug("Getting db_manager")
        return self._db_manager

    @db_manager.setter
    def db_manager(self, value):
        self.log.debug("Setting db_manager")
        self._db_manager = value

    @property
    def browser(self):
        self.log.debug("Getting browser")
        return self._browser

    @browser.setter
    def browser(self, value):
        self.log.debug("Setting browser")
        self._browser = value

    @property
    def blacklist_tags(self):
        self.log.debug("Getting blacklist_tags")
        return self._blacklist_tags

    @blacklist_tags.setter
    def blacklist_tags(self, value):
        self.log.debug("Setting blacklist_tags")
        self._blacklist_tags = value

    @property
    def supress_tags(self):
        self.log.debug("Getting supress_tags")
        return self._supress_tags

    @supress_tags.setter
    def supress_tags(self, value):
        self.log.debug("Setting supress_tags")
        self._supress_tags = value

    @property
    def error_list(self):
        self.log.debug("Getting error_list")
        return self._error_list

    @error_list.setter
    def error_list(self, value):
        self.log.debug("Setting error_list")
        self._error_list = value

    @property
    def last_error_code(self):
        self.log.debug("Getting last_error_code")
        return self._last_error_code

    @last_error_code.setter
    def last_error_code(self, value):
        self.log.debug("Setting last_error_code")
        self._last_error_code = value

    @property
    def blacklist_members(self):
        self.log.debug("Getting blacklist_member")
        return self._blacklist_members

    @blacklist_members.setter
    def blacklist_members(self, value):
        self.log.debug("Setting blacklist_members")
        self._blacklist_members = value

    @property
    def valid_options(self):
        self.log.debug("Getting valid_options")
        return self._valid_options

    @valid_options.setter
    def valid_options(self, value):
        self.log.debug("Setting valid_options")
        self._valid_options = value

    @property
    def operation(self):
        self.log.debug("Getting operation")
        return self._operation

    @operation.setter
    def operation(self, value):
        self.log.debug("Setting operation")
        self._operation = value


    # issue #299
    def get_remote_filesize(self, url, referer):
        print('Getting remote filesize...')
        # open with HEAD method, might be expensive
        req = PixivHelper.create_custom_request(url, self._config, referer, head=True)
        try:
            res = self._browser.open_novisit(req)
            file_size = int(res.info()['Content-Length'])
        except KeyError:
            file_size = -1
            PixivHelper.print_and_log('info', "\tNo file size information!")
        except mechanize.HTTPError as e:
            # fix Issue #503
            # handle http errors explicit by code
            if int(e.code) in (404, 500):
                file_size = -1
                PixivHelper.print_and_log('info', "\tNo file size information!")
            else:
                raise

        print("Remote filesize = {0} ({1} Bytes)".format(PixivHelper.sizeInStr(file_size), file_size))
        return file_size


    # -T04------For download file
    def download_image(self, url, filename, referer, overwrite, max_retry, backup_old_file=False, image=None, page=None):
        '''return download result and filename if ok'''
        temp_error_code = None
        retry_count = 0
        while retry_count <= max_retry:
            res = None
            req = None
            try:
                try:
                    if not overwrite and not self._config.alwaysCheckFileSize:
                        print('\rChecking local filename...', end=' ')
                        if os.path.exists(filename) and os.path.isfile(filename):
                            PixivHelper.print_and_log('info', "\rLocal file exists: {0}".format(filename.encode('utf-8')))
                            return (PixivConstant.PIXIVUTIL_SKIP_DUPLICATE, filename)

                    file_size = self.get_remote_filesize(url, referer)

                    # check if existing ugoira file exists
                    if filename.endswith(".zip"):
                        # non-converted zip (no animation.json)
                        if os.path.exists(filename) and os.path.isfile(filename):
                            old_size = os.path.getsize(filename)
                            # update for #451, always return identical?
                            check_result = PixivHelper.checkFileExists(overwrite, filename, file_size, old_size, backup_old_file)
                            if self._config.createUgoira:
                                self.handle_ugoira(image, filename)
                            return (check_result, filename)
                        # converted to ugoira (has animation.json)
                        ugo_name = filename[:-4] + ".ugoira"
                        if os.path.exists(ugo_name) and os.path.isfile(ugo_name):
                            old_size = PixivHelper.getUgoiraSize(ugo_name)
                            check_result = PixivHelper.checkFileExists(overwrite, ugo_name, file_size, old_size, backup_old_file)
                            if check_result != PixivConstant.PIXIVUTIL_OK:
                                # try to convert existing file.
                                self.handle_ugoira(image, filename)

                                return (check_result, filename)
                    elif os.path.exists(filename) and os.path.isfile(filename):
                        # other image? files
                        old_size = os.path.getsize(filename)
                        check_result = PixivHelper.checkFileExists(overwrite, filename, file_size, old_size, backup_old_file)
                        if check_result != PixivConstant.PIXIVUTIL_OK:
                            return (check_result, filename)

                    # check based on filename stored in DB using image id
                    if image is not None:
                        db_filename = None
                        if page is not None:
                            row = self._db_manager.selectImageByImageIdAndPage(image.imageId, page)
                            if row is not None:
                                db_filename = row[2]
                        else:
                            row = self._db_manager.selectImageByImageId(image.imageId)
                            if row is not None:
                                db_filename = row[3]
                        if db_filename is not None and os.path.exists(db_filename) and os.path.isfile(db_filename):
                            old_size = os.path.getsize(db_filename)
                            if file_size < 0:
                                file_size = self.get_remote_filesize(url, referer)
                            check_result = PixivHelper.checkFileExists(overwrite, db_filename, file_size, old_size, backup_old_file)
                            if check_result != PixivConstant.PIXIVUTIL_OK:
                                ugo_name = None
                                if db_filename.endswith(".zip"):
                                    ugo_name = filename[:-4] + ".ugoira"
                                    if self._config.createUgoira:
                                        self.handle_ugoira(image, db_filename)
                                if db_filename.endswith(".ugoira"):
                                    ugo_name = db_filename
                                    self.handle_ugoira(image, db_filename)

                                return (check_result, db_filename)

                    # actual download
                    (downloadedSize, filename) = self.perform_download(url, file_size, filename, overwrite, referer)
                    # set last-modified and last-accessed timestamp
                    if image is not None and self._config.setLastModified and filename is not None and os.path.isfile(filename):
                        ts = time.mktime(image.worksDateDateTime.timetuple())
                        os.utime(filename, (ts, ts))

                    # check the downloaded file size again
                    if file_size > 0 and downloadedSize != file_size:
                        raise PixivException("Incomplete Downloaded for {0}".format(url), PixivException.DOWNLOAD_FAILED_OTHER)
                    elif self._config.verifyImage and (filename.endswith(".jpg") or filename.endswith(".png") or filename.endswith(".gif")):
                        fp = None
                        try:
                            from PIL import Image, ImageFile
                            fp = open(filename, "rb")
                            # Fix Issue #269, refer to https://stackoverflow.com/a/42682508
                            ImageFile.LOAD_TRUNCATED_IMAGES = True
                            img = Image.open(fp)
                            img.load()
                            fp.close()
                            PixivHelper.print_and_log('info', ' Image verified.')
                        except BaseException:
                            if fp is not None:
                                fp.close()
                            PixivHelper.print_and_log('info', ' Image invalid, deleting...')
                            os.remove(filename)
                            raise
                    elif self._config.verifyImage and (filename.endswith(".ugoira") or filename.endswith(".zip")):
                        fp = None
                        try:
                            import zipfile
                            fp = open(filename, "rb")
                            zf = zipfile.ZipFile(fp)
                            zf.testzip()
                            fp.close()
                            PixivHelper.print_and_log('info', ' Image verified.')
                        except BaseException:
                            if fp is not None:
                                fp.close()
                            PixivHelper.print_and_log('info', ' Image invalid, deleting...')
                            os.remove(filename)
                            raise
                    else:
                        PixivHelper.print_and_log('info', ' done.')

                    # write to downloaded lists
                    if start_iv or self._config.createDownloadLists:
                        dfile = codecs.open(dfilename, 'a+', encoding='utf-8')
                        dfile.write(filename + "\n")
                        dfile.close()

                    return (PixivConstant.PIXIVUTIL_OK, filename)

                except urllib.error.HTTPError as httpError:
                    PixivHelper.print_and_log('error', '[download_image()] HTTP Error: {0} at {1}'.format(str(httpError), url))
                    if httpError.code == 404 or httpError.code == 502 or httpError.code == 500:
                        return (PixivConstant.PIXIVUTIL_NOT_OK, None)
                    temp_error_code = PixivException.DOWNLOAD_FAILED_NETWORK
                    raise
                except urllib.error.URLError as urlError:
                    PixivHelper.print_and_log('error', '[download_image()] URL Error: {0} at {1}'.format(str(urlError), url))
                    temp_error_code = PixivException.DOWNLOAD_FAILED_NETWORK
                    raise
                except IOError as ioex:
                    if ioex.errno == 28:
                        PixivHelper.print_and_log('error', ioex.args)
                        input("Press Enter to retry.")
                        return (PixivConstant.PIXIVUTIL_NOT_OK, None)
                    temp_error_code = PixivException.DOWNLOAD_FAILED_IO
                    raise
                except KeyboardInterrupt:
                    PixivHelper.print_and_log('info', 'Aborted by user request => Ctrl-C')
                    return (PixivConstant.PIXIVUTIL_ABORTED, None)
                finally:
                    if res is not None:
                        del res
                    if req is not None:
                        del req

            except BaseException:
                if temp_error_code is None:
                    temp_error_code = PixivException.DOWNLOAD_FAILED_OTHER
                self._last_error_code = temp_error_code
                exc_type, exc_value, exc_traceback = sys.exc_info()
                traceback.print_exception(exc_type, exc_value, exc_traceback)
                PixivHelper.print_and_log('error', 'Error at download_image(): {0} at {1} ({2})'.format(str(sys.exc_info()), url, self._last_error_code))

                if retry_count < max_retry:
                    retry_count = retry_count + 1
                    print("\rRetrying [{0}]...".format(retry_count), end=' ')
                    PixivHelper.printDelay(self._config.retryWait)
                else:
                    raise


    def perform_download(self, url, file_size, filename, overwrite, referer=None):
        if referer is None:
            referer = self._config, referer
        # actual download
        print('\rStart downloading...', end=' ')
        # fetch filesize
        req = PixivHelper.create_custom_request(url, self._config, referer)
        res = self._browser.open_novisit(req)
        if file_size < 0:
            try:
                file_size = int(res.info()['Content-Length'])
            except KeyError:
                file_size = -1
                PixivHelper.print_and_log('info', "\tNo file size information!")
        (downloadedSize, filename) = PixivHelper.downloadImage(url, filename, res, file_size, overwrite)
        return (downloadedSize, filename)


    #  Start of main processing logic
    def process_list(self, list_file_name=None, tags=None):

        result = None
        try:
            # Getting the list
            if self._config.processFromDb:
                PixivHelper.print_and_log('info', 'Processing from database.')
                if self._config.dayLastUpdated == 0:
                    result = self._db_manager.selectAllMember()
                else:
                    print('Select only last', self._config.dayLastUpdated, 'days.')
                    result = self._db_manager.selectMembersByLastDownloadDate(self._config.dayLastUpdated)
            else:
                PixivHelper.print_and_log('info', 'Processing from list file: {0}'.format(list_file_name))
                result = PixivListItem.parseList(list_file_name, self._config.rootDirectory)

            if os.path.exists("ignore_list.txt"):
                PixivHelper.print_and_log('info', 'Processing ignore list for member: {0}'.format("ignore_list.txt"))
                ignore_list = PixivListItem.parseList("ignore_list.txt", self._config.rootDirectory)
                for ignore in ignore_list:
                    for item in result:
                        if item.memberId == ignore.memberId:
                            result.remove(item)
                            break

            print("Found " + str(len(result)) + " items.")
            current_member = 1
            for item in result:
                retry_count = 0
                while True:
                    try:
                        prefix = "[{0} of {1}] ".format(current_member, len(result))
                        self.process_member(item.memberId, item.path, tags=tags, title_prefix=prefix)
                        current_member = current_member + 1
                        break
                    except KeyboardInterrupt:
                        raise
                    except BaseException:
                        if retry_count > self._config.retry:
                            PixivHelper.print_and_log('error', 'Giving up member_id: ' + str(item.memberId))
                            break
                        retry_count = retry_count + 1
                        print('Something wrong, retrying after 2 second (', retry_count, ')')
                        time.sleep(2)

                self._browser.clear_history()
                print('done.')
        except KeyboardInterrupt:
            raise
        except Exception as ex:
            self._last_error_code = getattr(ex, 'errorCode', -1)
            PixivHelper.print_and_log('error', 'Error at process_list(): {0}'.format(sys.exc_info()))
            print('Failed')
            raise


    def process_member(self, member_id, user_dir='', page=1, end_page=0, bookmark=False, tags=None, title_prefix=""):
        list_page = None

        PixivHelper.print_and_log('info', 'Processing Member Id: ' + str(member_id))
        if page != 1:
            PixivHelper.print_and_log('info', 'Start Page: ' + str(page))
        if end_page != 0:
            PixivHelper.print_and_log('info', 'End Page: ' + str(end_page))
            if self._config.numberOfPage != 0:
                PixivHelper.print_and_log('info', 'Number of page setting will be ignored')
        elif self.end_page_num != 0:
            PixivHelper.print_and_log('info', 'End Page from command line: ' + str(self.end_page_num))
        elif self._config.numberOfPage != 0:
            PixivHelper.print_and_log('info', 'End Page from config: ' + str(self._config.numberOfPage))

        self._config.loadConfig(path=self._configfile)

        # calculate the offset for display properties
        offset = 24  # new offset for AJAX call
        if self._browser._isWhitecube:
            offset = 50
        offset_start = (page - 1) * offset
        offset_stop = end_page * offset

        try:
            no_of_images = 1
            is_avatar_downloaded = False
            flag = True
            updated_limit_count = 0
            image_id = -1

            while flag:
                print('Page ', page)
                self.set_console_title("{0}MemberId: {1} Page: {2}".format(title_prefix, member_id, page))
                # Try to get the member page
                while True:
                    try:
                        (artist, list_page) = PixivBrowserFactory.getBrowser().getMemberPage(member_id, page, bookmark, tags)
                        break
                    except PixivException as ex:
                        self._last_error_code = ex.errorCode
                        PixivHelper.print_and_log('info', 'Member ID (' + str(member_id) + '): ' + str(ex))
                        if ex.errorCode == PixivException.NO_IMAGES:
                            pass
                        else:
                            if list_page is None:
                                list_page = ex.htmlPage
                            if list_page is not None:
                                PixivHelper.dumpHtml("Dump for " + str(member_id) + " Error Code " + str(ex.errorCode) + ".html", list_page)
                            if ex.errorCode == PixivException.USER_ID_NOT_EXISTS or ex.errorCode == PixivException.USER_ID_SUSPENDED:
                                self._db_manager.setIsDeletedFlagForMemberId(int(member_id))
                                PixivHelper.print_and_log('info', 'Set IsDeleted for MemberId: ' + str(member_id) + ' not exist.')
                                # self._db_manager.deleteMemberByMemberId(member_id)
                                # PixivHelper.printAndLog('info', 'Deleting MemberId: ' + str(member_id) + ' not exist.')
                            if ex.errorCode == PixivException.OTHER_MEMBER_ERROR:
                                PixivHelper.safePrint(ex.args)
                                self._error_list.append(dict(type="Member", id=str(member_id), message=ex.args, exception=ex))
                        return
                    except AttributeError:
                        # Possible layout changes, try to dump the file below
                        raise
                    except Exception:
                        exc_type, exc_value, exc_traceback = sys.exc_info()
                        traceback.print_exception(exc_type, exc_value, exc_traceback)
                        PixivHelper.print_and_log('error', 'Error at processing Artist Info: {0}'.format(sys.exc_info()))

                PixivHelper.safePrint('Member Name  : ' + artist.artistName)
                print('Member Avatar:', artist.artistAvatar)
                print('Member Token :', artist.artistToken)
                print('Member Background :', artist.artistBackground)
                print_offset_stop = offset_stop if offset_stop < artist.totalImages and offset_stop != 0 else artist.totalImages
                print('Processing images from {0} to {1} of {2}'.format(offset_start + 1, print_offset_stop, artist.totalImages))

                if not is_avatar_downloaded and self._config.downloadAvatar:
                    if user_dir == '':
                        target_dir = self._config.rootDirectory
                    else:
                        target_dir = str(user_dir)

                    avatar_filename = PixivHelper.createAvatarFilename(artist, target_dir)
                    if not DEBUG_SKIP_PROCESS_IMAGE:
                        if artist.artistAvatar.find('no_profile') == -1:
                            self.download_image(artist.artistAvatar,
                                           avatar_filename,
                                           "https://www.pixiv.net/",
                                           self._config.overwrite,
                                           self._config.retry,
                                           self._config.backupOldFile)
                        # Issue #508
                        if artist.artistBackground is not None and artist.artistBackground.startswith("http"):
                            bg_name = PixivHelper.createBackgroundFilenameFromAvatarFilename(avatar_filename)
                            self.download_image(artist.artistBackground,
                                           bg_name, "https://www.pixiv.net/",
                                           self._config.overwrite,
                                           self._config.retry,
                                           self._config.backupOldFile)
                    is_avatar_downloaded = True

                self._db_manager.updateMemberName(member_id, artist.artistName)

                if not artist.haveImages:
                    PixivHelper.print_and_log('info', "No image found for: " + str(member_id))
                    flag = False
                    continue

                result = PixivConstant.PIXIVUTIL_NOT_OK
                for image_id in artist.imageList:
                    print('#' + str(no_of_images))
                    if not self._config.overwrite:
                        r = self._db_manager.selectImageByMemberIdAndImageId(member_id, image_id)
                        if r is not None and not self._config.alwaysCheckFileSize:
                            print('Already downloaded:', image_id)
                            updated_limit_count = updated_limit_count + 1
                            if updated_limit_count > self._config.checkUpdatedLimit:
                                if self._config.checkUpdatedLimit != 0 and not self._config.alwaysCheckFileExists:
                                    print('Skipping member:', member_id)
                                    self._db_manager.updateLastDownloadedImage(member_id, image_id)

                                    del list_page
                                    self._browser.clear_history()
                                    return
                            gc.collect()
                            continue

                    retry_count = 0
                    while True:
                        try:
                            if artist.totalImages > 0:
                                # PixivHelper.safePrint("Total Images = " + str(artist.totalImages))
                                total_image_page_count = artist.totalImages
                                if offset_stop > 0 and offset_stop < total_image_page_count:
                                    total_image_page_count = offset_stop
                                total_image_page_count = total_image_page_count - offset_start
                                # PixivHelper.safePrint("Total Images Offset = " + str(total_image_page_count))
                            else:
                                total_image_page_count = ((page - 1) * 20) + len(artist.imageList)
                            title_prefix_img = "{0}MemberId: {1} Page: {2} Image {3}+{4} of {5}".format(title_prefix,
                                                                                                        member_id,
                                                                                                        page,
                                                                                                        no_of_images,
                                                                                                        updated_limit_count,
                                                                                                        total_image_page_count)
                            if not DEBUG_SKIP_PROCESS_IMAGE:
                                result = self.process_image(artist, image_id, user_dir, bookmark, title_prefix=title_prefix_img)
                                self.wait()

                            break
                        except KeyboardInterrupt:
                            result = PixivConstant.PIXIVUTIL_KEYBOARD_INTERRUPT
                            break
                        except BaseException:
                            if retry_count > self._config.retry:
                                PixivHelper.print_and_log('error', "Giving up image_id: " + str(image_id))
                                return
                            retry_count = retry_count + 1
                            print("Stuff happened, trying again after 2 second (", retry_count, ")")
                            exc_type, exc_value, exc_traceback = sys.exc_info()
                            traceback.print_exception(exc_type, exc_value, exc_traceback)
                            self.log.exception('Error at process_member(): ' + str(sys.exc_info()) + ' Member Id: ' + str(member_id))
                            time.sleep(2)

                    no_of_images = no_of_images + 1

                    if result == PixivConstant.PIXIVUTIL_KEYBOARD_INTERRUPT:
                        choice = input("Keyboard Interrupt detected, continue to next image (Y/N)")
                        if choice.upper() == 'N':
                            PixivHelper.print_and_log("info", "Member: " + str(member_id) + ", processing aborted")
                            flag = False
                            break
                        else:
                            continue

                    # return code from process image
                    if result == PixivConstant.PIXIVUTIL_SKIP_OLDER:
                        PixivHelper.print_and_log("info", "Reached older images, skippin to next member.")
                        flag = False
                        break

                if artist.isLastPage:
                    print("Last Page")
                    flag = False

                page = page + 1

                # page limit checking
                if end_page > 0 and page > end_page:
                    print("Page limit reached (from endPage limit =" + str(end_page) + ")")
                    flag = False
                else:
                    if self.np_is_valid:  # Yavos: overwriting config-data
                        if page > self.end_page_num and self.end_page_num > 0:
                            print("Page limit reached (from command line =" + str(self.end_page_num) + ")")
                            flag = False
                    elif page > self._config.numberOfPage and self._config.numberOfPage > 0:
                        print("Page limit reached (from config =" + str(self._config.numberOfPage) + ")")
                        flag = False

                del artist
                del list_page
                self._browser.clear_history()
                gc.collect()

            if image_id > 0:
                self._db_manager.updateLastDownloadedImage(member_id, image_id)
                log_message = 'last image_id: ' + str(image_id)
            else:
                log_message = 'no images were found'
            print('Done.\n')
            self.log.info('Member_id: ' + str(member_id) + ' complete, ' + log_message)
        except KeyboardInterrupt:
            raise
        except BaseException:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_traceback)
            PixivHelper.print_and_log('error', 'Error at process_member(): {0}'.format(sys.exc_info()))
            try:
                if list_page is not None:
                    dump_filename = 'Error page for member {0} at page {1}.html'.format(member_id, page)
                    PixivHelper.dumpHtml(dump_filename, list_page)
                    PixivHelper.print_and_log('error', "Dumping html to: {0}".format(dump_filename))
            except BaseException:
                PixivHelper.print_and_log('error', 'Cannot dump page for member_id: {0}'.format(member_id))
            raise


    def process_image(self, artist=None, image_id=None, user_dir='', bookmark=False, search_tags='', title_prefix="", bookmark_count=-1, image_response_count=-1):

        parse_big_image = None
        parse_medium_page = None
        image = None
        result = None
        referer = 'https://www.pixiv.net/member_illust.php?mode=medium&illust_id=' + str(image_id)
        filename = 'no-filename-{0}.tmp'.format(image_id)

        try:
            print('Processing Image Id:', image_id)

            # check if already downloaded. images won't be downloaded twice - needed in process_image to catch any download
            r = self._db_manager.selectImageByImageId(image_id, cols='save_name')
            exists = False
            in_db = False
            if r is not None:
                exists = True
                in_db = True
            if r is not None and self._config.alwaysCheckFileExists:
                exists = self._db_manager.cleanupFileExists(r[0])

            if r is not None and not self._config.alwaysCheckFileSize and exists:
                if not self._config.overwrite and exists:
                    print('Already downloaded:', image_id)
                    gc.collect()
                    return PixivConstant.PIXIVUTIL_SKIP_DUPLICATE

            # get the medium page
            try:
                (image, parse_medium_page) = PixivBrowserFactory.getBrowser().getImagePage(image_id=image_id,
                                                                                           parent=artist,
                                                                                           from_bookmark=bookmark,
                                                                                           bookmark_count=bookmark_count)
                if len(title_prefix) > 0:
                    self.set_console_title("{0} ImageId: {1}".format(title_prefix, image.imageId))
                else:
                    self.set_console_title("MemberId: {0} ImageId: {1}".format(image.artist.artistId, image.imageId))

            except PixivException as ex:
                self._last_error_code = ex.errorCode
                self._error_list.append(dict(type="Image", id=str(image_id), message=ex.args, exception=ex))
                if ex.errorCode == PixivException.UNKNOWN_IMAGE_ERROR:
                    PixivHelper.safePrint(ex.args)
                elif ex.errorCode == PixivException.SERVER_ERROR:
                    PixivHelper.print_and_log('error', 'Giving up image_id (medium): ' + str(image_id))
                elif ex.errorCode > 2000:
                    PixivHelper.print_and_log('error', 'Image Error for ' + str(image_id) + ': ' + ex.args)
                if parse_medium_page is not None:
                    dump_filename = 'Error medium page for image ' + str(image_id) + '.html'
                    PixivHelper.dumpHtml(dump_filename, parse_medium_page)
                    PixivHelper.print_and_log('error', 'Dumping html to: ' + dump_filename)
                else:
                    PixivHelper.print_and_log('error', 'Image ID (' + str(image_id) + '): ' + str(ex))
                PixivHelper.print_and_log('error', 'Stack Trace: {0}'.format(str(sys.exc_info())))
                return PixivConstant.PIXIVUTIL_NOT_OK
            except Exception as ex:
                PixivHelper.print_and_log('error', 'Image ID (' + str(image_id) + '): ' + str(ex))
                if parse_medium_page is not None:
                    dump_filename = 'Error medium page for image ' + str(image_id) + '.html'
                    PixivHelper.dumpHtml(dump_filename, parse_medium_page)
                    PixivHelper.print_and_log('error', 'Dumping html to: ' + dump_filename)
                PixivHelper.print_and_log('error', 'Stack Trace: {0}'.format(str(sys.exc_info())))
                return PixivConstant.PIXIVUTIL_NOT_OK

            download_image_flag = True

            # date validation and blacklist tag validation
            if self._config.dateDiff > 0:
                if image.worksDateDateTime != datetime.datetime.fromordinal(1).replace(tzinfo=datetime_z.utc):
                    if image.worksDateDateTime < (datetime.datetime.today() - datetime.timedelta(self._config.dateDiff)).replace(tzinfo=datetime_z.utc):
                        PixivHelper.print_and_log('info', 'Skipping image_id: ' + str(image_id) + ' because contains older than: ' + str(self._config.dateDiff) + ' day(s).')
                        download_image_flag = False
                        result = PixivConstant.PIXIVUTIL_SKIP_OLDER

            if self._config.useBlacklistTags:
                for item in self._blacklist_tags:
                    if item in image.imageTags:
                        PixivHelper.print_and_log('info', 'Skipping image_id: ' + str(image_id) + ' because contains blacklisted tags: ' + item)
                        download_image_flag = False
                        result = PixivConstant.PIXIVUTIL_SKIP_BLACKLIST
                        break

            if self._config.useBlacklistMembers:
                if str(image.originalArtist.artistId) in self._blacklist_members:
                    PixivHelper.print_and_log('info', 'Skipping image_id: ' + str(image_id) + ' because contains blacklisted member id: ' + str(image.originalArtist.artistId))
                    download_image_flag = False
                    result = PixivConstant.PIXIVUTIL_SKIP_BLACKLIST

            if download_image_flag:
                if artist is None:
                    PixivHelper.safePrint('Member Name  : ' + image.artist.artistName)
                    print('Member Avatar:', image.artist.artistAvatar)
                    print('Member Token :', image.artist.artistToken)
                    print('Member Background :', image.artist.artistBackground)
                PixivHelper.safePrint("Title: " + image.imageTitle)
                PixivHelper.safePrint("Tags : " + ', '.join(image.imageTags))
                PixivHelper.safePrint("Date : " + str(image.worksDateDateTime))
                print("Mode :", image.imageMode)

                # get bookmark count
                if ("%bookmark_count%" in self._config.filenameFormat or "%image_response_count%" in self._config.filenameFormat) and image.bookmark_count == -1:
                    print("Parsing bookmark page", end=' ')
                    bookmark_url = 'https://www.pixiv.net/bookmark_detail.php?illust_id=' + str(image_id)
                    parse_bookmark_page = PixivBrowserFactory.getBrowser().getPixivPage(bookmark_url)
                    image.ParseBookmarkDetails(parse_bookmark_page)
                    parse_bookmark_page.decompose()
                    del parse_bookmark_page
                    print("Bookmark Count :", str(image.bookmark_count))
                    self._browser.back()

                if self._config.useSuppressTags:
                    for item in self._supress_tags:
                        if item in image.imageTags:
                            image.imageTags.remove(item)

                # get manga page
                if image.imageMode == 'manga' or image.imageMode == 'big':
                    while True:
                        try:
                            big_url = 'https://www.pixiv.net/member_illust.php?mode={0}&illust_id={1}'.format(image.imageMode, image_id)
                            parse_big_image = PixivBrowserFactory.getBrowser().getPixivPage(big_url, referer)
                            if parse_big_image is not None:
                                image.ParseImages(page=parse_big_image, _br=PixivBrowserFactory.getExistingBrowser())
                                parse_big_image.decompose()
                                del parse_big_image
                            break
                        except Exception as ex:
                            self._error_list.append(dict(type="Image", id=str(image_id), message=ex.args, exception=ex))
                            PixivHelper.print_and_log('info', 'Image ID (' + str(image_id) + '): ' + str(traceback.format_exc()))
                            try:
                                if parse_big_image is not None:
                                    dump_filename = 'Error Big Page for image ' + str(image_id) + '.html'
                                    PixivHelper.dumpHtml(dump_filename, parse_big_image)
                                    PixivHelper.print_and_log('error', 'Dumping html to: ' + dump_filename)
                            except BaseException:
                                PixivHelper.print_and_log('error', 'Cannot dump big page for image_id: ' + str(image_id))
                            return PixivConstant.PIXIVUTIL_NOT_OK

                    if image.imageMode == 'manga':
                        print("Page Count :", image.imageCount)

                if user_dir == '':  # Yavos: use config-options
                    target_dir = self._config.rootDirectory
                else:  # Yavos: use filename from list
                    target_dir = str(user_dir)

                result = PixivConstant.PIXIVUTIL_OK
                manga_files = dict()
                page = 0
                for img in image.imageUrls:
                    print('Image URL :', img)
                    url = os.path.basename(img)
                    split_url = url.split('.')
                    if split_url[0].startswith(str(image_id)):
                        # Yavos: filename will be added here if given in list
                        filename_format = self._config.filenameFormat
                        if image.imageMode == 'manga':
                            filename_format = self._config.filenameMangaFormat

                        filename = PixivHelper.makeFilename(filename_format, image, tagsSeparator=self._config.tagsSeparator, tagsLimit=self._config.tagsLimit, fileUrl=url, bookmark=bookmark, searchTags=search_tags)
                        filename = PixivHelper.sanitizeFilename(filename, target_dir)

                        if image.imageMode == 'manga' and self._config.createMangaDir:
                            manga_page = __re_manga_page.findall(filename)
                            if len(manga_page) > 0:
                                splitted_filename = filename.split(manga_page[0][0], 1)
                                splitted_manga_page = manga_page[0][0].split("_p", 1)
                                filename = splitted_filename[0] + splitted_manga_page[0] + os.sep + "_p" + splitted_manga_page[1] + splitted_filename[1]

                        PixivHelper.print_and_log('info', 'Filename  : {0}'.format(filename))

                        result = PixivConstant.PIXIVUTIL_NOT_OK
                        try:
                            (result, filename) = self.download_image(img, filename, referer, self._config.overwrite, self._config.retry, self._config.backupOldFile, image, page)

                            if result == PixivConstant.PIXIVUTIL_NOT_OK:
                                PixivHelper.print_and_log('error', 'Image url not found/failed to download: ' + str(image.imageId))
                            elif result == PixivConstant.PIXIVUTIL_ABORTED:
                                raise KeyboardInterrupt()

                            manga_files[page] = filename
                            page = page + 1

                        except urllib.error.URLError:
                            PixivHelper.print_and_log('error', 'Error when download_image(), giving up url: {0}'.format(img))
                        print('')

                if self._config.writeImageInfo or self._config.writeImageJSON:
                    filename_info_format = self._config.filenameInfoFormat or self._config.filenameFormat
                    info_filename = PixivHelper.makeFilename(filename_info_format, image, tagsSeparator=self._config.tagsSeparator,
                                                        tagsLimit=self._config.tagsLimit, fileUrl=url, appendExtension=False, bookmark=bookmark,
                                                        searchTags=search_tags)
                    info_filename = PixivHelper.sanitizeFilename(info_filename, target_dir)
                    # trim _pXXX
                    info_filename = re.sub(r'_p?\d+$', '', info_filename)
                    if self._config.writeImageInfo:
                        image.WriteInfo(info_filename + ".txt")
                    if self._config.writeImageJSON:
                        image.WriteJSON(info_filename + ".json")

                if image.imageMode == 'ugoira_view':
                    if self._config.writeUgoiraInfo:
                        image.WriteUgoiraData(filename + ".js")
                    # Handle #451
                    if self._config.createUgoira and (result == PixivConstant.PIXIVUTIL_OK or result == PixivConstant.PIXIVUTIL_SKIP_DUPLICATE):
                        self.handle_ugoira(image, filename)

                if self._config.writeUrlInDescription:
                    PixivHelper.writeUrlInDescription(image, self._config.urlBlacklistRegex, self._config.urlDumpFilename)

            if in_db and not exists:
                result = PixivConstant.PIXIVUTIL_CHECK_DOWNLOAD  # There was something in the database which had not been downloaded

            # Only save to db if all images is downloaded completely
            if result == PixivConstant.PIXIVUTIL_OK or result == PixivConstant.PIXIVUTIL_SKIP_DUPLICATE or result == PixivConstant.PIXIVUTIL_SKIP_LOCAL_LARGER:
                try:
                    self._db_manager.insertImage(image.artist.artistId, image.imageId, image.imageMode)
                except BaseException:
                    PixivHelper.print_and_log('error', 'Failed to insert image id:{0} to DB'.format(image.imageId))

                self._db_manager.updateImage(image.imageId, image.imageTitle, filename, image.imageMode)

                if len(manga_files) > 0:
                    for page in manga_files:
                        self._db_manager.insertMangaImage(image_id, page, manga_files[page])

                # map back to PIXIVUTIL_OK (because of ugoira file check)
                result = 0

            if image is not None:
                del image
            gc.collect()
            # clearall()
            print('\n')
            return result
        except KeyboardInterrupt:
            raise
        except Exception as ex:
            self._last_error_code = getattr(ex, 'errorCode', -1)
            exc_type, exc_value, exc_traceback = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_traceback)
            PixivHelper.print_and_log('error', 'Error at process_image(): {0}'.format(image_id))
            PixivHelper.print_and_log('error', 'Exception: {0}'.format(sys.exc_info()))

            if parse_medium_page is not None:
                dump_filename = 'Error medium page for image ' + str(image_id) + '.html'
                PixivHelper.dumpHtml(dump_filename, parse_medium_page)
                PixivHelper.print_and_log('error', 'Dumping html to: {0}'.format(dump_filename))

            raise


    def handle_ugoira(self, image, filename):
        if filename.endswith(".zip"):
            ugo_name = filename[:-4] + ".ugoira"
        else:
            ugo_name = filename
        if not os.path.exists(ugo_name):
            PixivHelper.print_and_log('info', "Creating ugoira archive => " + ugo_name)
            image.CreateUgoira(filename)
            # set last-modified and last-accessed timestamp
            if self._config.setLastModified and ugo_name is not None and os.path.isfile(ugo_name):
                ts = time.mktime(image.worksDateDateTime.timetuple())
                os.utime(ugo_name, (ts, ts))

        if self._config.deleteZipFile and os.path.exists(filename):
            PixivHelper.print_and_log('info', "Deleting zip file => " + filename)
            os.remove(filename)

        if self._config.createGif:
            gif_filename = ugo_name[:-7] + ".gif"
            if not os.path.exists(gif_filename):
                PixivHelper.ugoira2gif(ugo_name, gif_filename, self._config.deleteUgoira, image=image)
        if self._config.createApng:
            gif_filename = ugo_name[:-7] + ".png"
            if not os.path.exists(gif_filename):
                PixivHelper.ugoira2apng(ugo_name, gif_filename, self._config.deleteUgoira, image=image)
        if self._config.createWebm:
            gif_filename = ugo_name[:-7] + ".webm"
            if not os.path.exists(gif_filename):
                PixivHelper.ugoira2webm(ugo_name,
                                    gif_filename,
                                    self._config.deleteUgoira,
                                    self._config.ffmpeg,
                                    self._config.ffmpegCodec,
                                    self._config.ffmpegParam,
                                    "webm",
                                    image)
        if self._config.createWebp:
            gif_filename = ugo_name[:-7] + ".webp"
            if not os.path.exists(gif_filename):
                PixivHelper.ugoira2webm(ugo_name,
                                    gif_filename,
                                    self._config.deleteUgoira,
                                    self._config.ffmpeg,
                                    self._config.webpCodec,
                                    self._config.webpParam,
                                    "webp",
                                    image)


    def process_tags(self, tags, page=1, end_page=0, wild_card=True, title_caption=False,
                   start_date=None, end_date=None, use_tags_as_dir=False, member_id=None,
                   bookmark_count=None, oldest_first=False):

        search_page = None
        i = page
        updated_limit_count = 0

        try:
            self._config.loadConfig(path=self._configfile)  # Reset the config for root directory

            search_tags = PixivHelper.decode_tags(tags)

            if use_tags_as_dir:
                print("Save to each directory using query tags.")
                self._config.rootDirectory += os.sep + PixivHelper.sanitizeFilename(search_tags)

            tags = PixivHelper.encode_tags(tags)

            images = 1
            last_image_id = -1
            skipped_count = 0

            offset = 20
            if self._browser._isWhitecube:
                offset = 50
            start_offset = (page - 1) * offset
            stop_offset = end_page * offset

            PixivHelper.print_and_log('info', 'Searching for: (' + search_tags + ") " + tags)
            flag = True
            while flag:
                (t, search_page) = self._browser.getSearchTagPage(tags, i,
                                                      wild_card,
                                                      title_caption,
                                                      start_date,
                                                      end_date,
                                                      member_id,
                                                      oldest_first,
                                                      page)
                if len(t.itemList) == 0:
                    print('No more images')
                    flag = False
                else:
                    for item in t.itemList:
                        last_image_id = item.imageId
                        print('Image #' + str(images))
                        print('Image Id:', str(item.imageId))
                        print('Bookmark Count:', str(item.bookmarkCount))
                        if bookmark_count is not None and bookmark_count > item.bookmarkCount:
                            PixivHelper.print_and_log('info', 'Skipping imageId= {0} because less than bookmark count limit ({1} > {2}).'.format(item.imageId, bookmark_count, item.bookmarkCount))
                            skipped_count = skipped_count + 1
                            continue
                        result = 0
                        while True:
                            try:
                                if t.availableImages > 0:
                                    # PixivHelper.safePrint("Total Images: " + str(t.availableImages))
                                    total_image = t.availableImages
                                    if(stop_offset > 0 and stop_offset < total_image):
                                        total_image = stop_offset
                                    total_image = total_image - start_offset
                                    # PixivHelper.safePrint("Total Images Offset: " + str(total_image))
                                else:
                                    total_image = ((i - 1) * 20) + len(t.itemList)
                                title_prefix = "Tags:{0} Page:{1} Image {2}+{3} of {4}".format(tags, i, images, skipped_count, total_image)
                                if member_id is not None:
                                    title_prefix = "MemberId: {0} Tags:{1} Page:{2} Image {3}+{4} of {5}".format(member_id,
                                                                                                                  tags, i,
                                                                                                                  images,
                                                                                                                  skipped_count,
                                                                                                                  total_image)
                                result = PixivConstant.PIXIVUTIL_OK
                                if not DEBUG_SKIP_PROCESS_IMAGE:
                                    result = self.process_image(None, item.imageId, search_tags=search_tags, title_prefix=title_prefix, bookmark_count=item.bookmarkCount, image_response_count=item.imageResponse)
                                    self.wait()
                                break
                            except KeyboardInterrupt:
                                result = PixivConstant.PIXIVUTIL_KEYBOARD_INTERRUPT
                                break
                            except http.client.BadStatusLine:
                                print("Stuff happened, trying again after 2 second...")
                                time.sleep(2)

                        images = images + 1
                        if result == PixivConstant.PIXIVUTIL_SKIP_DUPLICATE or result == PixivConstant.PIXIVUTIL_SKIP_LOCAL_LARGER:
                            updated_limit_count = updated_limit_count + 1
                            if updated_limit_count > self._config.checkUpdatedLimit:
                                if self._config.checkUpdatedLimit != 0 and not self._config.alwaysCheckFileExists:
                                    PixivHelper.safePrint("Skipping tags: {0}".format(tags))
                                    self._browser.clear_history()
                                    return
                            gc.collect()
                            continue
                        elif result == PixivConstant.PIXIVUTIL_KEYBOARD_INTERRUPT:
                            choice = input("Keyboard Interrupt detected, continue to next image (Y/N)")
                            if choice.upper() == 'N':
                                PixivHelper.print_and_log("info", "Tags: " + tags + ", processing aborted")
                                flag = False
                                break
                            else:
                                continue

                self._browser.clear_history()

                i = i + 1

                del search_page

                if end_page != 0 and end_page < i:
                    PixivHelper.print_and_log('info', "End Page reached: " + str(end_page))
                    flag = False
                if t.isLastPage:
                    PixivHelper.print_and_log('info', "Last page: " + str(i - 1))
                    flag = False
                if self._config.enableInfiniteLoop and i == 1001 and not oldest_first:
                    if last_image_id > 0:
                        # get the last date
                        PixivHelper.print_and_log('info', "Hit page 1000, trying to get workdate for last image id: " + str(last_image_id))
                        referer = 'https://www.pixiv.net/member_illust.php?mode=medium&illust_id=' + str(last_image_id)
                        parse_medium_page = PixivBrowserFactory.getBrowser().getPixivPage(referer)
                        image = PixivImage(iid=last_image_id, page=parse_medium_page, dateFormat=self._config.dateFormat)
                        _last_date = image.worksDateDateTime.strftime("%Y-%m-%d")
                        # hit the last page
                        PixivHelper.print_and_log('info', "Hit page 1000, looping back to page 1 with ecd: " + str(_last_date))
                        i = 1
                        end_date = _last_date
                        flag = True
                        last_image_id = -1
                    else:
                        PixivHelper.print_and_log('info', "No more image in the list.")
                        flag = False

            print('done')
        except KeyboardInterrupt:
            raise
        except BaseException:
            msg = 'Error at process_tags() at page {0}: {1}'.format(i, sys.exc_info())
            PixivHelper.print_and_log('error', msg)
            try:
                if search_page is not None:
                    dump_filename = 'Error page for search tags {0} at page {1}.html'.format(tags, i)
                    PixivHelper.dumpHtml(dump_filename, search_page)
                    PixivHelper.print_and_log('error', "Dumping html to: " + dump_filename)
            except BaseException:
                PixivHelper.print_and_log('error', 'Cannot dump page for search tags:' + search_tags)
            raise


    def process_tags_list(self, filename, page=1, end_page=0, wild_card=True,
                          oldest_first=False, bookmark_count=None,
                          start_date=None, end_date=None):

        try:
            print("Reading:", filename)
            l = PixivTags.parseTagsList(filename)
            for tag in l:
                self.process_tags(tag, page=page, end_page=end_page, wild_card=wild_card,
                             use_tags_as_dir=self._config.useTagsAsDir, oldest_first=oldest_first,
                             bookmark_count=bookmark_count, start_date=start_date, end_date=end_date)
        except KeyboardInterrupt:
            raise
        except Exception as ex:
            self._last_error_code = getattr(ex, 'errorCode', -1)
            PixivHelper.print_and_log('error', 'Error at process_tags_list(): {0}'.format(sys.exc_info()))
            raise


    def process_image_bookmark(self, hide='n', start_page=1, end_page=0, tag='', sorting=None):
        try:
            print("Importing image bookmarks...")
            totalList = list()
            image_count = 1

            if hide == 'n':
                totalList.extend(self.get_image_bookmark(False, start_page, end_page, tag, sorting))
            elif hide == 'y':
                # public and private image bookmarks
                totalList.extend(self.get_image_bookmark(False, start_page, end_page, tag, sorting))
                totalList.extend(self.get_image_bookmark(True, start_page, end_page, tag, sorting))
            else:
                totalList.extend(self.get_image_bookmark(True, start_page, end_page, tag, sorting))

            PixivHelper.print_and_log('info', "Found " + str(len(totalList)) + " image(s).")
            for item in totalList:
                print("Image #" + str(image_count))
                self.process_image(artist=None, image_id=item)
                image_count = image_count + 1
                self.wait()

            print("Done.\n")
        except KeyboardInterrupt:
            raise
        except BaseException:
            PixivHelper.print_and_log('error', 'Error at process_image_bookmark(): {0}'.format(sys.exc_info()))
            raise


    def get_image_bookmark(self, hide, start_page=1, end_page=0, tag='', sorting=None):
        """Get user's image bookmark"""
        total_list = list()
        i = start_page
        while True:
            if end_page != 0 and i > end_page:
                print("Page Limit reached: " + str(end_page))
                break

            url = 'https://www.pixiv.net/bookmark.php?p=' + str(i)
            if hide:
                url = url + "&rest=hide"
            # Implement #468 default is desc, only for your own bookmark.
            if sorting in ('asc', 'date_d', 'date'):
                url = url + "&order=" + sorting
            if tag is not None and len(tag) > 0:
                url = url + '&tag=' + PixivHelper.encode_tags(tag)
            PixivHelper.print_and_log('info', "Importing user's bookmarked image from page " + str(i))
            PixivHelper.print_and_log('info', "Source URL: " + url)

            page = self._browser.open(url)
            parse_page = BeautifulSoup(page.read())
            l = PixivBookmark.parseImageBookmark(parse_page)
            total_list.extend(l)
            if len(l) == 0:
                print("No more images.")
                break
            else:
                print(" found " + str(len(l)) + " images.")

            i = i + 1

            parse_page.decompose()
            del parse_page

        return total_list


    def get_bookmarks(self, hide, start_page=1, end_page=0, member_id=None):
        """Get User's bookmarked artists """
        total_list = list()
        i = start_page
        while True:
            if end_page != 0 and i > end_page:
                print('Limit reached')
                break
            PixivHelper.print_and_log('info', 'Exporting page ' + str(i))
            url = 'https://www.pixiv.net/bookmark.php?type=user&p=' + str(i)
            if hide:
                url = url + "&rest=hide"
            if member_id:
                url = url + "&id=" + member_id
            PixivHelper.print_and_log('info', "Source URL: " + url)

            page = self._browser.open_with_retry(url)
            parse_page = BeautifulSoup(page.read())
            l = PixivBookmark.parseBookmark(parse_page)
            if len(l) == 0:
                print('No more data')
                break
            total_list.extend(l)
            i = i + 1
            print(str(len(l)), 'items')
        return total_list


    def process_bookmark(self, hide='n', start_page=1, end_page=0):
        try:
            total_list = list()
            if hide != 'o':
                print("Importing Bookmarks...")
                total_list.extend(self.get_bookmarks(False, start_page, end_page))
            if hide != 'n':
                print("Importing Private Bookmarks...")
                total_list.extend(self.get_bookmarks(True, start_page, end_page))
            print("Result: ", str(len(total_list)), "items.")
            i = 0
            current_member = 1
            for item in total_list:
                print("%d/%d\t%f %%" % (i, len(total_list), 100.0 * i / float(len(total_list))))
                i += 1
                prefix = "[{0} of {1}]".format(current_member, len(total_list))
                self.process_member(item.memberId, item.path, title_prefix=prefix)
                current_member = current_member + 1
            print("%d/%d\t%f %%" % (i, len(total_list), 100.0 * i / float(len(total_list))))
        except KeyboardInterrupt:
            raise
        except BaseException:
            PixivHelper.print_and_log('error', 'Error at process_bookmark(): {0}'.format(sys.exc_info()))
            raise


    def export_bookmark(self, filename, hide='n', start_page=1, end_page=0, member_id=None):
        try:
            total_list = list()
            if hide != 'o':
                print("Importing Bookmarks...")
                total_list.extend(self.get_bookmarks(False, start_page, end_page, member_id))
            if hide != 'n':
                print("Importing Private Bookmarks...")
                total_list.extend(self.get_bookmarks(True, start_page, end_page, member_id))
            print("Result: ", str(len(total_list)), "items.")
            PixivBookmark.exportList(total_list, filename)
        except KeyboardInterrupt:
            raise
        except BaseException:
            PixivHelper.print_and_log('error', 'Error at export_bookmark(): {0}'.format(sys.exc_info()))
            raise


    def process_new_illust_from_bookmark(self, page_num=1, end_page_num=0):
        try:
            print("Processing New Illust from bookmark")
            i = page_num
            image_count = 1
            flag = True
            while flag:
                print("Page #" + str(i))
                url = 'https://www.pixiv.net/bookmark_new_illust.php?p=' + str(i)
                if self._config.r18mode:
                    url = 'https://www.pixiv.net/bookmark_new_illust_r18.php?p=' + str(i)

                PixivHelper.print_and_log('info', "Source URL: " + url)
                page = self._browser.open(url)
                parsed_page = BeautifulSoup(page.read())
                pb = PixivNewIllustBookmark(parsed_page)
                if not pb.haveImages:
                    print("No images!")
                    break

                for image_id in pb.imageList:
                    print("Image #" + str(image_count))
                    result = self.process_image(artist=None, image_id=int(image_id))
                    image_count = image_count + 1

                    if result == PixivConstant.PIXIVUTIL_SKIP_OLDER:
                        flag = False
                        break

                    self.wait()
                i = i + 1

                parsed_page.decompose()
                del parsed_page

                # Non premium is only limited to 100 page
                # Premium user might be limited to 5000, refer to issue #112
                if (end_page_num != 0 and i > end_page_num) or i > 5000 or pb.isLastPage:
                    print("Limit or last page reached.")
                    flag = False

            print("Done.")
        except KeyboardInterrupt:
            raise
        except BaseException:
            PixivHelper.print_and_log('error', 'Error at process_new_illust_from_bookmark(): {0}'.format(sys.exc_info()))
            raise


    def process_from_group(self, group_id, limit=0, process_external=True):
        try:
            print("Download by Group Id")
            if limit != 0:
                print("Limit: {0}".format(limit))
            if process_external:
                print("Include External Image: {0}".format(process_external))

            max_id = 0
            image_count = 0
            flag = True
            while flag:
                url = "https://www.pixiv.net/group/images.php?format=json&max_id={0}&id={1}".format(max_id, group_id)
                PixivHelper.print_and_log('info', "Getting images from: {0}".format(url))
                json_response = self._browser.open(url)
                group_data = PixivGroup(json_response)
                max_id = group_data.maxId
                if group_data.imageList is not None and len(group_data.imageList) > 0:
                    for image in group_data.imageList:
                        if image_count > limit and limit != 0:
                            flag = False
                            break
                        print("Image #{0}".format(image_count))
                        print("ImageId: {0}".format(image))
                        self.process_image(image_id=image)
                        image_count = image_count + 1
                        self.wait()

                if process_external and group_data.externalImageList is not None and len(group_data.externalImageList) > 0:
                    for image_data in group_data.externalImageList:
                        if image_count > limit and limit != 0:
                            flag = False
                            break
                        print("Image #{0}".format(image_count))
                        print("Member Id   : {0}".format(image_data.artist.artistId))
                        PixivHelper.safePrint("Member Name  : " + image_data.artist.artistName)
                        print("Member Token : {0}".format(image_data.artist.artistToken))
                        print("Image Url   : {0}".format(image_data.imageUrls[0]))

                        filename = PixivHelper.makeFilename(self._config.filenameFormat, imageInfo=image_data,
                                                            tagsSeparator=self._config.tagsSeparator,
                                                            tagsLimit=self._config.tagsLimit, fileUrl=image_data.imageUrls[0])
                        filename = PixivHelper.sanitizeFilename(filename, self._config.rootDirectory)
                        PixivHelper.safePrint("Filename  : " + filename)
                        (result, filename) = self.download_image(image_data.imageUrls[0], filename, url, self._config.overwrite, self._config.retry, self._config.backupOldFile)
                        if self._config.setLastModified and filename is not None and os.path.isfile(filename):
                            ts = time.mktime(image_data.worksDateDateTime.timetuple())
                            os.utime(filename, (ts, ts))

                        image_count = image_count + 1

                if (group_data.imageList is None or len(group_data.imageList) == 0) and \
                   (group_data.externalImageList is None or len(group_data.externalImageList) == 0):
                    flag = False
                print("")

        except BaseException:
            PixivHelper.print_and_log('error', 'Error at process_from_group(): {0}'.format(sys.exc_info()))
            raise


    def header(self):
        print('PixivDownloader2 version', PixivConstant.PIXIVUTIL_VERSION)
        print(PixivConstant.PIXIVUTIL_LINK)
        print('Donate at', PixivConstant.PIXIVUTIL_DONATE)


    def get_start_and_end_number(self, start_only=False):

        page_num = input('Start Page (default=1): ') or 1
        try:
            page_num = int(page_num)
        except BaseException:
            print("Invalid page number:", page_num)
            raise

        end_page_num = 0
        if self.np_is_valid:
            end_page_num = self.end_page_num
        else:
            end_page_num = self._config.numberOfPage

        if not start_only:
            end_page_num = input('End Page (default=' + str(end_page_num) + ', 0 for no limit): ') or end_page_num
            try:
                end_page_num = int(end_page_num)
                if page_num > end_page_num and end_page_num != 0:
                    print("page_num is bigger than end_page_num, assuming as page count.")
                    end_page_num = page_num + end_page_num
            except BaseException:
                print("Invalid end page number:", end_page_num)
                raise

        return page_num, end_page_num


    def get_start_and_end_number_from_args(self, args, offset=0, start_only=False):
        page_num = 1
        if len(args) > 0 + offset:
            try:
                page_num = int(args[0 + offset])
                print("Start Page =", str(page_num))
            except BaseException:
                print("Invalid page number:", args[0 + offset])
                raise

        end_page_num = 0
        if self.np_is_valid:
            end_page_num = self.end_page_num
        else:
            end_page_num = self._config.numberOfPage

        if not start_only:
            if len(args) > 1 + offset:
                try:
                    end_page_num = int(args[1 + offset])
                    if page_num > end_page_num and end_page_num != 0:
                        print("page_num is bigger than end_page_num, assuming as page count.")
                        end_page_num = page_num + end_page_num
                    print("End Page =", str(end_page_num))
                except BaseException:
                    print("Invalid end page number:", args[1 + offset])
                    raise
        return page_num, end_page_num


    def check_date_time(self, input_date):
        split = input_date.split("-")
        return datetime.date(int(split[0]), int(split[1]), int(split[2])).isoformat()


    def get_start_and_end_date(self):
        start_date = None
        end_date = None
        while True:
            try:
                start_date = input('Start Date [YYYY-MM-DD]: ') or None
                if start_date is not None:
                    start_date = self.check_date_time(start_date)
                break
            except Exception as e:
                print(str(e))

        while True:
            try:
                end_date = input('End Date [YYYY-MM-DD]: ') or None
                if end_date is not None:
                    end_date = self.check_date_time(end_date)
                break
            except Exception as e:
                print(str(e))

        return start_date, end_date


    def menu(self):
        self.set_console_title()
        self.header()
        print('1. Download by member_id')
        print('2. Download by image_id')
        print('3. Download by tags')
        print('4. Download from list')
        print('5. Download from bookmarked artists (/bookmark.php?type=user)')
        print('6. Download from bookmarked images (/bookmark.php)')
        print('7. Download from tags list')
        print('8. Download new illust from bookmarked members (/bookmark_new_illust.php)')
        print('9. Download by Title/Caption')
        print('10. Download by Tag and Member Id')
        print('11. Download Member Bookmark (/bookmark.php?id=)')
        print('12. Download by Group Id')
        print('------------------------')
        print('f1. Download from supported artists (FANBOX)')
        print('f2. Download by artist id (FANBOX)')
        print('------------------------')
        print('d. Manage database')
        print('e. Export online bookmark')
        print('m. Export online user bookmark')
        print('r. Reload config.ini')
        print('p. Print config.ini')
        print('x. Exit')

        return input('Input: ').strip()


    def menu_download_by_member_id(self, opisvalid, args):
        self.log.info('Member id mode.')
        current_member = 1
        page = 1
        end_page = 0

        if opisvalid and len(args) > 0:
            for member_id in args:
                try:
                    prefix = "[{0} of {1}] ".format(current_member, len(args))
                    test_id = int(member_id)
                    self.process_member(test_id, title_prefix=prefix)
                    current_member = current_member + 1
                except BaseException:
                    PixivHelper.print_and_log('error', "Member ID: {0} is not valid".format(member_id))
                    self._last_error_code = -1
                    continue
        else:
            member_ids = input('Member ids: ')
            (page, end_page) = self.get_start_and_end_number()

            member_ids = PixivHelper.getIdsFromCsv(member_ids, sep=" ")
            PixivHelper.print_and_log('info', "Member IDs: {0}".format(member_ids))
            for member_id in member_ids:
                prefix = "[{0} of {1}] ".format(current_member, len(member_ids))
                self.process_member(member_id, page=page, end_page=end_page, title_prefix=prefix)
                current_member = current_member + 1


    def menu_download_by_member_bookmark(self, opisvalid, args):
        self.log.info('Member Bookmark mode.')
        page = 1
        end_page = 0
        i = 0
        current_member = 1
        if opisvalid and len(args) > 0:
            valid_ids = list()
            for member_id in args:
                print("%d/%d\t%f %%" % (i, len(args), 100.0 * i / float(len(args))))
                i += 1
                try:
                    test_id = int(member_id)
                    valid_ids.append(test_id)
                except BaseException:
                    PixivHelper.print_and_log('error', "Member ID: {0} is not valid".format(member_id))
                    self._last_error_code = -1
                    continue
            if self._browser._myId in valid_ids:
                PixivHelper.print_and_log('error', "Member ID: {0} is your own id, use option 6 instead.".format(self._browser._myId))
            for mid in valid_ids:
                prefix = "[{0} of {1}] ".format(current_member, len(valid_ids))
                self.process_member(mid, bookmark=True, tags=None, title_prefix=prefix)
                current_member = current_member + 1

        else:
            member_id = input('Member id: ')
            tags = input('Filter Tags: ')
            (page, end_page) = self.get_start_and_end_number()
            if self._browser._myId == int(member_id):
                PixivHelper.print_and_log('error', "Member ID: {0} is your own id, use option 6 instead.".format(member_id))
            else:
                self.process_member(member_id.strip(), page=page, end_page=end_page, bookmark=True, tags=tags)


    def menu_download_by_image_id(self, opisvalid, args):
        self.log.info('Image id mode.')
        if opisvalid and len(args) > 0:
            for image_id in args:
                try:
                    test_id = int(image_id)
                    self.process_image(None, test_id)
                except BaseException:
                    PixivHelper.print_and_log('error', "Image ID: {0} is not valid".format(image_id))
                    self._last_error_code = -1
                    continue
        else:
            image_ids = input('Image ids: ')
            image_ids = PixivHelper.getIdsFromCsv(image_ids, sep=" ")
            for image_id in image_ids:
                self.process_image(None, int(image_id))


    def menu_download_by_tags(self, opisvalid, args):
        self.log.info('tags mode.')
        page = 1
        end_page = 0
        start_date = None
        end_date = None
        bookmark_count = None
        oldest_first = False
        wildcard = True
        if opisvalid and len(args) > 0:
            wildcard = args[0]
            if wildcard.lower() == 'y':
                wildcard = True
            else:
                wildcard = False
            (page, end_page) = self.get_start_and_end_number_from_args(args, 1)
            tags = " ".join(args[3:])
        else:
            tags = PixivHelper.uni_input('Tags: ')
            bookmark_count = input('Bookmark Count: ') or None
            wildcard = input('Use Partial Match (s_tag) [y/n]: ') or 'n'
            if wildcard.lower() == 'y':
                wildcard = True
            else:
                wildcard = False
            oldest_first = input('Oldest first[y/n]: ') or 'n'
            if oldest_first.lower() == 'y':
                oldest_first = True
            else:
                oldest_first = False

            (page, end_page) = self.get_start_and_end_number()
            (start_date, end_date) = self.get_start_and_end_date()
        if bookmark_count is not None:
            bookmark_count = int(bookmark_count)
        self.process_tags(tags.strip(), page, end_page, wildcard, start_date=start_date, end_date=end_date,
                    use_tags_as_dir=self._config.useTagsAsDir, bookmark_count=bookmark_count, oldest_first=oldest_first)


    def menu_download_by_title_caption(self, opisvalid, args):
        self.log.info('Title/Caption mode.')
        page = 1
        end_page = 0
        start_date = None
        end_date = None
        if opisvalid and len(args) > 0:
            (page, end_page) = self.get_start_and_end_number_from_args(args)
            tags = " ".join(args[2:])
        else:
            tags = PixivHelper.uni_input('Title/Caption: ')
            (page, end_page) = self.get_start_and_end_number()
            (start_date, end_date) = self.get_start_and_end_date()

        self.process_tags(tags.strip(), page, end_page, wild_card=False, title_caption=True, start_date=start_date, end_date=end_date, use_tags_as_dir=self._config.useTagsAsDir)


    def menu_download_by_tag_and_member_id(self, opisvalid, args):
        self.log.info('Tag and MemberId mode.')
        member_id = 0
        tags = None
        page = 1
        end_page = 0

        if opisvalid and len(args) >= 2:
            try:
                member_id = int(args[0])
            except BaseException:
                PixivHelper.print_and_log('error', "Member ID: {0} is not valid".format(member_id))
                self._last_error_code = -1
                return

            (page, end_page) = self.get_start_and_end_number_from_args(args, 1)
            tags = " ".join(args[3:])
            PixivHelper.safePrint("Looking tags: " + tags + " from memberId: " + str(member_id))
        else:
            member_id = input('Member Id: ')
            tags = PixivHelper.uni_input('Tag      : ')
            (page, end_page) = self.get_start_and_end_number()

        self.process_tags(tags.strip(), page, end_page, member_id=int(member_id), use_tags_as_dir=self._config.useTagsAsDir)


    def menu_download_from_list(self, opisvalid, args):
        self.log.info('Batch mode.')

        list_file_name = self._config.downloadListDirectory + os.sep + 'list.txt'
        tags = None
        if opisvalid and self._operation == '4' and len(args) > 0:
            test_file_name = self._config.downloadListDirectory + os.sep + args[0]
            if os.path.exists(test_file_name):
                list_file_name = test_file_name
            if len(args) > 1:
                tags = args[1]
        else:
            test_tags = PixivHelper.uni_input('Tag : ')
            if len(test_tags) > 0:
                tags = test_tags

        if tags is not None and len(tags) > 0:
            PixivHelper.safePrint("Processing member id from {0} for tags: {1}".format(list_file_name, tags))
        else:
            PixivHelper.safePrint("Processing member id from {0}".format(list_file_name))

        self.process_list(list_file_name, tags)


    def menu_download_from_online_user_bookmark(self, opisvalid, args):
        self.log.info('User Bookmarked Artist mode.')
        start_page = 1
        end_page = 0
        hide = 'n'
        if opisvalid:
            if len(args) > 0:
                arg = args[0].lower()
                if arg == 'y' or arg == 'n' or arg == 'o':
                    hide = arg
                else:
                    print("Invalid args: ", args)
                    return
                (start_page, end_page) = self.get_start_and_end_number_from_args(args, offset=1)
        else:
            arg = input("Include Private bookmarks [y/n/o]: ") or 'n'
            arg = arg.lower()
            if arg == 'y' or arg == 'n' or arg == 'o':
                hide = arg
            else:
                print("Invalid args: ", arg)
                return
            (start_page, end_page) = self.get_start_and_end_number()
        self.process_bookmark(hide, start_page, end_page)


    def menu_download_from_online_image_bookmark(self, opisvalid, args):
        self.log.info("User's Image Bookmark mode.")
        start_page = 1
        end_page = 0
        hide = 'n'
        tag = ''
        sorting = 'desc'

        if opisvalid and len(args) > 0:
            hide = args[0].lower()
            if hide not in ('y', 'n', 'o'):
                print("Invalid args: ", args)
                return
            (start_page, end_page) = self.get_start_and_end_number_from_args(args, offset=1)
            if len(args) > 3:
                tag = args[3]
            if len(args) > 4:
                sorting = args[4].lower()
                if sorting not in ('asc', 'desc', 'date', 'date_d'):
                    print("Invalid sorting order: ", sorting)
                    return
        else:
            hide = input("Include Private bookmarks [y/n/o]: ") or 'n'
            hide = hide.lower()
            if hide not in ('y', 'n', 'o'):
                print("Invalid args: ", hide)
                return
            tag = input("Tag (default=All Images): ") or ''
            (start_page, end_page) = self.get_start_and_end_number()
            sorting = input("Sort Order [asc/desc/date/date_d]: ") or 'desc'
            sorting = sorting.lower()
            if sorting not in ('asc', 'desc', 'date', 'date_d'):
                print("Invalid sorting order: ", sorting)
                return

        self.process_image_bookmark(hide, start_page, end_page, tag, sorting)


    def menu_download_from_tags_list(self, opisvalid, args):
        self.log.info('Taglist mode.')
        page = 1
        end_page = 0
        oldest_first = False
        wildcard = True
        bookmark_count = None
        start_date = None
        end_date = None

        if opisvalid and len(args) > 0:
            filename = args[0]
            (page, end_page) = self.get_start_and_end_number_from_args(args, offset=1)
        else:
            filename = input("Tags list filename [tags.txt]: ") or './tags.txt'
            wildcard = input('Use Wildcard[y/n]: ') or 'n'
            if wildcard.lower() == 'y':
                wildcard = True
            else:
                wildcard = False
            oldest_first = input('Oldest first[y/n]: ') or 'n'
            if oldest_first.lower() == 'y':
                oldest_first = True
            else:
                oldest_first = False
            bookmark_count = input('Bookmark Count: ') or None
            (page, end_page) = self.get_start_and_end_number()
            (start_date, end_date) = self.get_start_and_end_date()
        if bookmark_count is not None:
            bookmark_count = int(bookmark_count)

        self.process_tags_list(filename, page, end_page, wild_card=wildcard, oldest_first=oldest_first,
                          bookmark_count=bookmark_count, start_date=start_date, end_date=end_date)


    def menu_download_new_illust_from_bookmark(self, opisvalid, args):
        self.log.info('New Illust from Bookmark mode.')

        if opisvalid:
            (page_num, end_page_num) = self.get_start_and_end_number_from_args(args, offset=0)
        else:
            (page_num, end_page_num) = self.get_start_and_end_number()

        self.process_new_illust_from_bookmark(page_num, end_page_num)


    def menu_download_by_group_id(self, opisvalid, args):
        self.log.info('Group mode.')
        process_external = False
        limit = 0

        if opisvalid and len(args) > 0:
            group_id = args[0]
            limit = int(args[1])
            if args[2].lower() == 'y':
                process_external = True
        else:
            group_id = input("Group Id: ")
            limit = int(input("Limit: "))
            arg = input("Process External Image [y/n]: ") or 'n'
            arg = arg.lower()
            if arg == 'y':
                process_external = True

        self.process_from_group(group_id, limit, process_external)


    def menu_export_online_bookmark(self, opisvalid, args):
        self.log.info('Export Bookmark mode.')
        hide = "y"  # y|n|o
        filename = "export.txt"

        if opisvalid and len(args) > 0:
            arg = args[0]
            if len(args) > 1:
                filename = args[1]
        else:
            filename = input("Filename: ")
            arg = input("Include Private bookmarks [y/n/o]: ") or 'n'
            arg = arg.lower()

        if arg == 'y' or arg == 'n' or arg == 'o':
            hide = arg
        else:
            print("Invalid args: ", arg)

        self.export_bookmark(filename, hide)


    def menu_export_online_user_bookmark(self, opisvalid, args):
        self.log.info('Export Bookmark mode.')
        member_id = ''
        filename = "export-user.txt"

        if opisvalid and len(args) > 0:
            arg = args[0]
            if len(args) > 1:
                filename = args[1]
            else:
                filename = "export-user-{0}.txt".format(arg)
        else:
            filename = input("Filename: ") or filename
            arg = input("Member Id: ") or ''
            arg = arg.lower()

        if arg.isdigit():
            member_id = arg
        else:
            print("Invalid args: ", arg)

        self.export_bookmark(filename, 'n', 1, 0, member_id)


    def menu_fanbox_download_supported_artist(self, op_is_valid, args):
        self.log.info('Download FANBOX Supported Artists mode.')
        end_page = 0

        if op_is_valid and len(args) > 0:
            end_page = int(args[0])
        else:
            end_page = input("Max Page = ") or 0
            end_page = int(end_page)

        result = self._browser.fanboxGetSupportedUsers()
        if len(result.supportedArtist) == 0:
            PixivHelper.print_and_log("info", "No supported artist!")
            return
        PixivHelper.print_and_log("info", "Found {0} supported artist(s)".format(len(result.supportedArtist)))
        print(result.supportedArtist)

        for artist_id in result.supportedArtist:
            self.processFanboxArtist(artist_id, end_page)


    def processFanboxArtist(self, artist_id, end_page):
        current_page = 1
        next_url = None
        image_count = 1
        while(True):
            PixivHelper.print_and_log("info", "Processing {0}, page {1}".format(artist_id, current_page))
            result_artist = self._browser.fanboxGetPostsFromArtist(artist_id, next_url)

            for post in result_artist.posts:
                print("#{0}".format(image_count))
                print("Post  = {0}".format(post.imageId))
                print("Title = {0}".format(post.imageTitle))
                print("Type  = {0}".format(post.type))
                print("Created Date  = {0}".format(post.worksDate))
                print("Is Restricted = {0}".format(post.is_restricted))
                # cover image
                if post.coverImageUrl is not None:
                    # fake the image_url for filename compatibility, add post id and pagenum
                    fake_image_url = post.coverImageUrl.replace("{0}/cover/".format(post.imageId), "{0}_".format(post.imageId))
                    filename = PixivHelper.makeFilename(self._config.filenameFormat,
                                                        post,
                                                        artistInfo=result_artist,
                                                        tagsSeparator=self._config.tagsSeparator,
                                                        tagsLimit=self._config.tagsLimit,
                                                        fileUrl=fake_image_url,
                                                        bookmark=None,
                                                        searchTags='')
                    filename = PixivHelper.sanitizeFilename(filename, self._config.rootDirectory)

                    print("Downloading cover from {0}".format(post.coverImageUrl))
                    print("Saved to {0}".format(filename))

                    referer = "https://www.pixiv.net/fanbox/creator/{0}/post/{1}".format(artist_id, post.imageId)
                    # don't pass the post id and page number to skip db check
                    (result, filename) = self.download_image(post.coverImageUrl,
                                                        filename,
                                                        referer,
                                                        self._config.overwrite,
                                                        self._config.retry,
                                                        self._config.backupOldFile)

                else:
                    PixivHelper.print_and_log("info", "No Cover Image for post: {0}.".format(post.imageId))

                # images
                if post.type in PixivModelFanbox.FanboxPost._supportedType:
                    self.processFanboxImages(post, result_artist)
                image_count = image_count + 1

            if not result_artist.hasNextPage:
                PixivHelper.print_and_log("info", "No more post for {0}".format(artist_id))
                break
            current_page = current_page + 1
            if end_page > 0 and current_page > end_page:
                PixivHelper.print_and_log("info", "Reaching page limit for {0}, limit {1}".format(artist_id, end_page))
                break
            next_url = result_artist.nextUrl
            if next_url is None:
                PixivHelper.print_and_log("info", "No more next page for {0}".format(artist_id))
                break


    def processFanboxImages(self, post, result_artist):
        if post.is_restricted:
            PixivHelper.print_and_log("info", "Skipping post: {0} due to restricted post.".format(post.imageId))
            return
        if post.images is None or len(post.images) == 0:
            PixivHelper.print_and_log("info", "No Image available in post: {0}.".format(post.imageId))
            # return
        else:
            current_page = 0
            print("Image Count = {0}".format(len(post.images)))
            for image_url in post.images:
                # fake the image_url for filename compatibility, add post id and pagenum
                fake_image_url = image_url.replace("{0}/".format(post.imageId), "{0}_p{1}_".format(post.imageId, current_page))
                filename = PixivHelper.makeFilename(self._config.filenameMangaFormat,
                                                    post,
                                                    artistInfo=result_artist,
                                                    tagsSeparator=self._config.tagsSeparator,
                                                    tagsLimit=self._config.tagsLimit,
                                                    fileUrl=fake_image_url,
                                                    bookmark=None,
                                                    searchTags='')

                filename = PixivHelper.sanitizeFilename(filename, self._config.rootDirectory)
                referer = "https://www.pixiv.net/fanbox/creator/{0}/post/{1}".format(result_artist.artistId, post.imageId)

                print("Downloading image {0} from {1}".format(current_page, image_url))
                print("Saved to {0}".format(filename))

                # filesize detection and overwrite issue
                _oldvalue = self._config.alwaysCheckFileSize
                self._config.alwaysCheckFileSize = False
                # don't pass the post id and page number to skip db check
                (result, filename) = self.download_image(image_url,
                                                    filename,
                                                    referer,
                                                    False,  # self._config.overwrite somehow unable to get remote filesize
                                                    self._config.retry,
                                                    self._config.backupOldFile)

                self._config.alwaysCheckFileSize = _oldvalue
                current_page = current_page + 1

        # Implement #447
        if self._config.writeImageInfo:
            filename = PixivHelper.makeFilename(self._config.filenameInfoFormat,
                                                post,
                                                artistInfo=result_artist,
                                                tagsSeparator=self._config.tagsSeparator,
                                                tagsLimit=self._config.tagsLimit,
                                                fileUrl="{0}".format(post.imageId),
                                                bookmark=None,
                                                searchTags='')

            filename = PixivHelper.sanitizeFilename(filename, self._config.rootDirectory)
            post.WriteInfo(filename + ".txt")


    def menu_fanbox_download_by_artist_id(self, op_is_valid, args):
        self.log.info('Download FANBOX by Artist ID mode.')
        end_page = 0
        artist_id = ''

        if op_is_valid and len(args) > 0:
            artist_id = str(int(args[0]))
            if len(args) > 1:
                end_page = args[1]
        else:
            artist_id = input("Artist ID = ")
            end_page = input("Max Page = ") or 0

        end_page = int(end_page)

        self.processFanboxArtist(artist_id, end_page)


    def menu_reload_config(self):
        self.log.info('Manual Reload Config.')
        self._config.loadConfig(path=self._configfile)


    def menu_print_config(self):
        self.log.info('Manual Reload Config.')
        self._config.printConfig()


    def set_console_title(self, title=''):
        set_title = 'PixivDownloader {0} {1}'.format(PixivConstant.PIXIVUTIL_VERSION, title)
        PixivHelper.setConsoleTitle(set_title)


    def setup_option_parser(self):
        self._valid_options = ('1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', 'f1', 'f2', 'd', 'e', 'm')
        parser = OptionParser()
        parser.add_option('-s', '--startaction', dest='startaction',
                          help='Action you want to load your program with:       ' +
                                '1 - Download by member_id                       ' +
                                '2 - Download by image_id                        ' +
                                '3 - Download by tags                            ' +
                                '4 - Download from list                          ' +
                                '5 - Download from user bookmark                 ' +
                                '6 - Download from user\'s image bookmark        ' +
                                '7 - Download from tags list                     ' +
                                '8 - Download new illust from bookmark           ' +
                                '9 - Download by Title/Caption                   ' +
                                '10 - Download by Tag and Member Id              ' +
                                '11 - Download images from Member Bookmark       ' +
                                '12 - Download images by Group Id                ' +
                                'f1 - Download from supported artists (FANBOX)   ' +
                                'f2 - Download by artist id (FANBOX)             ' +
                                'e - Export online bookmark                      ' +
                                'm - Export online user bookmark                 ' +
                                'd - Manage database')
        parser.add_option('-x', '--exitwhendone', dest='exitwhendone',
                          help='Exit programm when done. (only useful when not using DB-Manager)',
                          action='store_true', default=False)
        parser.add_option('-i', '--irfanview', dest='start_iv',
                          help='start IrfanView after downloading images using downloaded_on_%date%.txt',
                          action='store_true', default=False)
        parser.add_option('-n', '--numberofpages', dest='numberofpages',
                          help='temporarily overwrites numberOfPage set in config.ini')
        parser.add_option('-c', '--config', dest='configlocation',
                          help='load the config file from a custom location',
                          default=None)

        return parser


    # Main thread #
    def main_loop(self, ewd, op_is_valid, selection, np_is_valid_local, args):

        while True:
            try:
                if len(self._error_list) > 0:
                    print("Unknown errors from previous _operation")
                    for err in self._error_list:
                        message = err["type"] + ": " + str(err["id"]) + " ==> " + err["message"]
                        PixivHelper.print_and_log('error', message)
                    self._error_list = list()
                    self._last_error_code = 1

                if op_is_valid:  # Yavos (next 3 lines): if commandline then use it
                    selection = self._operation
                else:
                    selection = self.menu()

                if selection == '1':
                    self.menu_download_by_member_id(op_is_valid, args)
                elif selection == '2':
                    self.menu_download_by_image_id(op_is_valid, args)
                elif selection == '3':
                    self.menu_download_by_tags(op_is_valid, args)
                elif selection == '4':
                    self.menu_download_from_list(op_is_valid, args)
                elif selection == '5':
                    self.menu_download_from_online_user_bookmark(op_is_valid, args)
                elif selection == '6':
                    self.menu_download_from_online_image_bookmark(op_is_valid, args)
                elif selection == '7':
                    self.menu_download_from_tags_list(op_is_valid, args)
                elif selection == '8':
                    self.menu_download_new_illust_from_bookmark(op_is_valid, args)
                elif selection == '9':
                    self.menu_download_by_title_caption(op_is_valid, args)
                elif selection == '10':
                    self.menu_download_by_tag_and_member_id(op_is_valid, args)
                elif selection == '11':
                    self.menu_download_by_member_bookmark(op_is_valid, args)
                elif selection == '12':
                    self.menu_download_by_group_id(op_is_valid, args)
                elif selection == 'e':
                    self.menu_export_online_bookmark(op_is_valid, args)
                elif selection == 'm':
                    self.menu_export_online_user_bookmark(op_is_valid, args)
                elif selection == 'd':
                    self._db_manager.main()
                elif selection == 'r':
                    self.menu_reload_config()
                elif selection == 'p':
                    self.menu_print_config()
                # PIXIV FANBOX
                elif selection == 'f1':
                    self.menu_fanbox_download_supported_artist(op_is_valid, args)
                elif selection == 'f2':
                    self.menu_fanbox_download_by_artist_id(op_is_valid, args)
                # END PIXIV FANBOX
                elif selection == '-all':
                    if not np_is_valid_local:
                        np_is_valid_local = True
                        self.end_page_num = 0
                        print('download all mode activated')
                    else:
                        np_is_valid_local = False
                        print('download mode reset to', self._config.numberOfPage, 'pages')
                elif selection == 'x':
                    break

                if ewd:  # Yavos: added lines for "exit when done"
                    break
                op_is_valid = False  # Yavos: needed to prevent endless loop
            except KeyboardInterrupt:
                PixivHelper.print_and_log("info", "Keyboard Interrupt pressed, selection: {0}".format(selection))
                PixivHelper.clearScreen()
                print("Restarting...")
                selection = self.menu()
            except PixivException as ex:
                if ex.htmlPage is not None:
                    filename = PixivHelper.sanitizeFilename(ex.value)
                    PixivHelper.dumpHtml("Dump for {0}.html".format(filename), ex.htmlPage)
                raise  # keep old behaviour

        return np_is_valid_local, op_is_valid, selection


    def doLogin(self, password, username):
        result = False
        # store username/password for oAuth in case not stored in config.ini
        if username is not None and len(username) > 0:
            self._browser._username = username
        if password is not None and len(password) > 0:
            self._browser._password = password

        try:
            if len(self._config.cookie) > 0:
                result = self._browser.loginUsingCookie()

            if not result:
                result = self._browser.login(username, password)

        except BaseException:
            PixivHelper.print_and_log('error', 'Error at doLogin(): {0}'.format(str(sys.exc_info())))
            raise PixivException("Cannot Login!", PixivException.CANNOT_LOGIN)
        return result



    def probe(self):
        '''
        Check we can access the internet and everything is OK
        '''
        url = "https://www.google.com"
        self.log.info("Probing '%s'", url)
        ret = self._browser.open_with_retry(url)
        ret = str(ret.read())
        self.log.info("Fetched OK: %s", len(ret))


    def wait(self):
        # Issue#276: add random delay for each post.
        if self._config.downloadDelay > 0:
            delay = random.random() * self._config.downloadDelay
            print("Wait for {0:.3}s".format(delay))
            time.sleep(delay)