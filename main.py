#!/usr/bin/python
# -*- coding: utf-8 -*-
# pylint: disable=I0011, C, C0302, W0602, W0603, W0703, R0102, R1702, R0912, R0915


import codecs
import datetime
import gc
import getpass
import os
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

import pixivutil2.PixivBrowserFactory
import pixivutil2.PixivConfig
import pixivutil2.PixivConstant
import pixivutil2.PixivDBManager
import pixivutil2.PixivHelper
import pixivutil2.PixivModelFanbox
from pixivutil2.PixivException import PixivException
from pixivutil2.PixivModel import PixivBookmark
from pixivutil2.PixivModel import PixivGroup
from pixivutil2.PixivModel import PixivImage
from pixivutil2.PixivModel import PixivListItem
from pixivutil2.PixivModel import PixivNewIllustBookmark
from pixivutil2.PixivModel import PixivTags

def patch_mechanize():

    # replace unenscape_charref implementation with our implementation due to bug.
    mechanize._html.unescape_charref = PixivHelper.unescape_charref


def set_terminal_encoding():
    try:
        stdin, stdout, stderr = sys.stdin, sys.stdout, sys.stderr
        reload(sys)
        sys.stdin, sys.stdout, sys.stderr = stdin, stdout, stderr
        sys.setdefaultencoding("utf-8")
    except Exception as e:
        pass  # swallow the exception

    if os.name == 'nt':
        # enable unicode support on windows console.
        import win_unicode_console

        # monkey patch for #305
        from ctypes import byref, c_ulong
        from win_unicode_console.streams import set_last_error, ERROR_SUCCESS, ReadConsoleW, get_last_error, ERROR_OPERATION_ABORTED, WinError
        from win_unicode_console.buffer import get_buffer
        EOF = b"\x1a\x00"

        def readinto_patch(self, b):
            bytes_to_be_read = len(b)
            if not bytes_to_be_read:
                return 0
            elif bytes_to_be_read % 2:
                raise ValueError("cannot read odd number of bytes from UTF-16-LE encoded console")

            buffers = get_buffer(b, writable=True)
            code_units_to_be_read = bytes_to_be_read // 2
            code_units_read = c_ulong()

            set_last_error(ERROR_SUCCESS)
            ReadConsoleW(self.handle, buffers, code_units_to_be_read, byref(code_units_read), None)
            last_error = get_last_error()
            if last_error == ERROR_OPERATION_ABORTED:
                time.sleep(0.1)  # wait for KeyboardInterrupt
            if last_error != ERROR_SUCCESS:
                raise WinError(last_error)

            if buffers[:len(EOF)] == EOF:
                return 0
            else:
                return 2 * code_units_read.value  # bytes read

        win_unicode_console.streams.WindowsConsoleRawReader.readinto = readinto_patch
        win_unicode_console.enable()

        # patch getpass.getpass() for windows to show '*'
        def win_getpass_with_mask(prompt='Password: ', stream=None):
            """Prompt for password with echo off, using Windows getch()."""
            if sys.stdin is not sys.__stdin__:
                return getpass.fallback_getpass(prompt, stream)
            import msvcrt
            for c in prompt:
                msvcrt.putch(c)
            pw = ""
            while 1:
                c = msvcrt.getch()
                if c == '\r' or c == '\n':
                    break
                if c == '\003':
                    raise KeyboardInterrupt
                if c == '\b':
                    pw = pw[:-1]
                    print("\b \b", end="")
                else:
                    pw = pw + c
                    print("*", end="")
            msvcrt.putch('\r')
            msvcrt.putch('\n')
            return pw

        getpass.getpass = win_getpass_with_mask

def main():
    set_terminal_encoding()
    patch_mechanize()

    set_console_title()
    header()

    # Option Parser
    global np_is_valid  # used in process image bookmark
    global np  # used in various places for number of page overwriting
    global start_iv  # used in download_image
    global dfilename
    global op
    global __br__
    global configfile
    global ERROR_CODE
    global __dbManager__
    global __valid_options

    parser = setup_option_parser()
    (options, args) = parser.parse_args()

    op = options.startaction
    if op in __valid_options:
        op_is_valid = True
    elif op is None:
        op_is_valid = False
    else:
        op_is_valid = False
        parser.error('%s is not valid operation' % op)
        # Yavos: use print option instead when program should be running even with this error

    ewd = options.exitwhendone
    configfile = options.configlocation

    try:
        if options.numberofpages is not None:
            np = int(options.numberofpages)
            np_is_valid = True
        else:
            np_is_valid = False
    except BaseException:
        np_is_valid = False
        parser.error('Value %s used for numberOfPage is not an integer.' % options.numberofpages)
        # Yavos: use print option instead when program should be running even with this error
        ### end new lines by Yavos ###

    __log__.info('###############################################################')
    if len(sys.argv) == 0:
        __log__.info('Starting with no argument..')
    else:
        __log__.info('Starting with argument: [%s].', " ".join(sys.argv))
    try:
        __config__.loadConfig(path=configfile)
        PixivHelper.setConfig(__config__)
    except BaseException:
        print('Failed to read configuration.')
        __log__.exception('Failed to read configuration.')

    PixivHelper.setLogLevel(__config__.logLevel)
    if __br__ is None:
        __br__ = PixivBrowserFactory.getBrowser(config=__config__)

    if __config__.checkNewVersion:
        PixivHelper.check_version()

    selection = None

    # Yavos: adding File for downloadlist
    now = datetime.date.today()
    dfilename = __config__.downloadListDirectory + os.sep + 'Downloaded_on_' + now.strftime('%Y-%m-%d') + '.txt'
    if not re.match(r'[a-zA-Z]:', dfilename):
        dfilename = PixivHelper.toUnicode(sys.path[0], encoding=sys.stdin.encoding) + os.sep + dfilename
        # dfilename = sys.path[0].rsplit('\\',1)[0] + '\\' + dfilename #Yavos: only useful for myself
    dfilename = dfilename.replace('\\\\', '\\')
    dfilename = dfilename.replace('\\', os.sep)
    dfilename = dfilename.replace(os.sep + 'library.zip' + os.sep + '.', '')

    directory = os.path.dirname(dfilename)
    if not os.path.exists(directory):
        os.makedirs(directory)
        __log__.info('Creating directory: %s', directory)

    # Yavos: adding IrfanView-Handling
    start_irfan_slide = False
    start_irfan_view = False
    if __config__.startIrfanSlide or __config__.startIrfanView:
        start_iv = True
        start_irfan_slide = __config__.startIrfanSlide
        start_irfan_view = __config__.startIrfanView
    elif options.start_iv is not None:
        start_iv = options.start_iv
        start_irfan_view = True
        start_irfan_slide = False

    try:
        __dbManager__ = PixivDBManager.PixivDBManager(target=__config__.dbPath, config=__config__)
        __dbManager__.createDatabase()

        if __config__.useList:
            list_txt = PixivListItem.parseList(__config__.downloadListDirectory + os.sep + 'list.txt', __config__.rootDirectory)
            __dbManager__.importList(list_txt)
            print("Updated " + str(len(list_txt)) + " items.")

        if __config__.overwrite:
            msg = 'Overwrite enabled.'
            PixivHelper.print_and_log('info', msg)

        if __config__.dayLastUpdated != 0 and __config__.processFromDb:
            PixivHelper.print_and_log('info',
                                    'Only process members where the last update is >= ' + str(__config__.dayLastUpdated) + ' days ago')

        if __config__.dateDiff > 0:
            PixivHelper.print_and_log('info', 'Only process image where day last updated >= ' + str(__config__.dateDiff))

        if __config__.useBlacklistTags:
            global __blacklistTags
            __blacklistTags = PixivTags.parseTagsList("blacklist_tags.txt")
            PixivHelper.print_and_log('info', 'Using Blacklist Tags: ' + str(len(__blacklistTags)) + " items.")

        if __config__.useBlacklistMembers:
            global __blacklistMembers
            __blacklistMembers = PixivTags.parseTagsList("blacklist_members.txt")
            PixivHelper.print_and_log('info', 'Using Blacklist Members: ' + str(len(__blacklistMembers)) + " members.")

        if __config__.useSuppressTags:
            global __suppressTags
            __suppressTags = PixivTags.parseTagsList("suppress_tags.txt")
            PixivHelper.print_and_log('info', 'Using Suppress Tags: ' + str(len(__suppressTags)) + " items.")

        if __config__.createWebm:
            import shlex
            cmd = "{0} -encoders".format(__config__.ffmpeg)
            ffmpeg_args = shlex.split(cmd)
            try:
                p = subprocess.Popen(ffmpeg_args, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
                buff = p.stdout.read()
                if buff.find(__config__.ffmpegCodec) == 0:
                    __config__.createWebm = False
                    PixivHelper.print_and_log('error', '{0}'.format("#" * 80))
                    PixivHelper.print_and_log('error', 'Missing {0} encoder, createWebm disabled.'.format(__config__.ffmpegCodec))
                    PixivHelper.print_and_log('error', 'Command used: {0}.'.format(cmd))
                    PixivHelper.print_and_log('info', 'Please download ffmpeg with {0} encoder enabled.'.format(__config__.ffmpegCodec))
                    PixivHelper.print_and_log('error', '{0}'.format("#" * 80))
            except Exception as ex:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                __config__.createWebm = False
                PixivHelper.print_and_log('error', '{0}'.format("#" * 80))
                PixivHelper.print_and_log('error', 'Failed to load ffmpeg, createWebm disabled: {0}'.format(exc_value))
                PixivHelper.print_and_log('error', 'Command used: {0}.'.format(cmd))
                PixivHelper.print_and_log('info', 'Please download ffmpeg with {0} encoder enabled.'.format(__config__.ffmpegCodec))
                PixivHelper.print_and_log('error', '{0}'.format("#" * 80))

        if __config__.useLocalTimezone:
            PixivHelper.print_and_log("info", "Using local timezone: {0}".format(PixivHelper.LocalUTCOffsetTimezone()))

        username = __config__.username
        if username == '':
            username = input('Username ? ')
        else:
            msg = 'Using Username: ' + username
            print(msg)
            __log__.info(msg)

        password = __config__.password
        if password == '':
            if os.name == 'nt':
                win_unicode_console.disable()
            password = getpass.getpass('Password ? ')
            if os.name == 'nt':
                win_unicode_console.enable()

        if np_is_valid and np != 0:  # Yavos: overwrite config-data
            msg = 'Limit up to: ' + str(np) + ' page(s). (set via commandline)'
            print(msg)
            __log__.info(msg)
        elif __config__.numberOfPage != 0:
            msg = 'Limit up to: ' + str(__config__.numberOfPage) + ' page(s).'
            print(msg)
            __log__.info(msg)

        result = doLogin(password, username)

        if result:
            np_is_valid, op_is_valid, selection = main_loop(ewd, op_is_valid, selection, np_is_valid, args)

            if start_iv:  # Yavos: adding start_irfan_view-handling
                PixivHelper.startIrfanView(dfilename, __config__.IrfanViewPath, start_irfan_slide, start_irfan_view)
        else:
            ERROR_CODE = PixivException.NOT_LOGGED_IN
    except PixivException as pex:
        PixivHelper.print_and_log('error', pex.message)
        ERROR_CODE = pex.errorCode
    except Exception as ex:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        __log__.exception('Unknown Error: %s', str(exc_value))
        ERROR_CODE = getattr(ex, 'errorCode', -1)
    finally:
        __dbManager__.close()
        if not ewd:  # Yavos: prevent input on exitwhendone
            if selection is None or selection != 'x':
                input('press enter to exit.')
        __log__.setLevel("INFO")
        __log__.info('EXIT: %s', ERROR_CODE)
        __log__.info('###############################################################')
        sys.exit(ERROR_CODE)


if __name__ == '__main__':
    main()
