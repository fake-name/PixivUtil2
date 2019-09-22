#!/usr/bin/python
# -*- coding: utf-8 -*-
# pylint: disable=I0011, C, C0302, W0602, W0603, W0703, R0102, R1702, R0912, R0915, R1075


import datetime
import getpass
import os
import re
import subprocess
import sys
import time
import traceback
import mechanize

import pixivutil2.PixivBrowserFactory
import pixivutil2.PixivConfig
import pixivutil2.PixivConstant
import pixivutil2.PixivDBManager
import pixivutil2.PixivHelper
import pixivutil2.PixivModelFanbox
from pixivutil2.PixivException import PixivException
from pixivutil2.PixivModel import PixivListItem
from pixivutil2.PixivModel import PixivTags
import pixivutil2.entry_point


def patch_mechanize():
    # replace unenscape_charref implementation with our implementation due to bug.
    mechanize._html.unescape_charref = pixivutil2.PixivHelper.unescape_charref


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
        from ctypes import byref
        from ctypes import c_ulong
        from win_unicode_console.streams import set_last_error
        from win_unicode_console.streams import ERROR_SUCCESS
        from win_unicode_console.streams import ReadConsoleW
        from win_unicode_console.streams import get_last_error
        from win_unicode_console.streams import ERROR_OPERATION_ABORTED
        from win_unicode_console.streams import WinError
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
    pixivutil2.PixivHelper.init_logging()
    cli_log = pixivutil2.PixivHelper.getLogger(prefix="CLI")
    interface = pixivutil2.entry_point.PixivUtil()

    interface.set_console_title()
    interface.header()

    # Option Parser
    # global np_is_valid  # used in process image bookmark
    # global np  # used in various places for number of page overwriting
    # global start_iv  # used in download_image
    # global dfilename
    # global op
    # global __br__
    # global configfile
    # global ERROR_CODE
    # global __dbManager__
    # global __valid_options

    parser = interface.setup_option_parser()
    options, args = parser.parse_args()

    op = options.startaction
    if op in interface.valid_options:
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

    cli_log.info('###############################################################')
    if len(sys.argv) == 0:
        cli_log.info('Starting with no argument..')
    else:
        cli_log.info('Starting with argument: [%s].', " ".join(sys.argv))
    try:
        interface.config.loadConfig(path=configfile)
        pixivutil2.PixivHelper.setConfig(interface.config)
    except BaseException:
        cli_log.info('Failed to read configuration.')
        cli_log.exception('Failed to read configuration.')

    pixivutil2.PixivHelper.setLogLevel(interface.config.logLevel)
    if interface.browser is None:
        interface.browser = pixivutil2.PixivBrowserFactory.getBrowser(config=interface.config)

    if interface.config.checkNewVersion:
        pixivutil2.PixivHelper.check_version()

    selection = None

    # Yavos: adding File for downloadlist
    now = datetime.date.today()
    dfilename = interface.config.downloadListDirectory + os.sep + 'Downloaded_on_' + now.strftime('%Y-%m-%d') + '.txt'
    if not re.match(r'[a-zA-Z]:', dfilename):
        dfilename = pixivutil2.PixivHelper.toUnicode(sys.path[0], encoding=sys.stdin.encoding) + os.sep + dfilename
        # dfilename = sys.path[0].rsplit('\\',1)[0] + '\\' + dfilename #Yavos: only useful for myself
    dfilename = dfilename.replace('\\\\', '\\')
    dfilename = dfilename.replace('\\', os.sep)
    dfilename = dfilename.replace(os.sep + 'library.zip' + os.sep + '.', '')

    directory = os.path.dirname(dfilename)
    if not os.path.exists(directory):
        os.makedirs(directory)
        cli_log.info('Creating directory: %s', directory)

    # Yavos: adding IrfanView-Handling
    start_irfan_slide = False
    start_irfan_view = False
    if interface.config.startIrfanSlide or interface.config.startIrfanView:
        start_iv = True
        start_irfan_slide = interface.config.startIrfanSlide
        start_irfan_view = interface.config.startIrfanView
    elif options.start_iv is not None:
        start_iv = options.start_iv
        start_irfan_view = True
        start_irfan_slide = False

    try:
        __dbManager__ = pixivutil2.PixivDBManager.PixivDBManager(target=interface.config.dbPath, config=interface.config)
        __dbManager__.createDatabase()

        if interface.config.useList:
            list_txt = PixivListItem.parseList(interface.config.downloadListDirectory + os.sep + 'list.txt', interface.config.rootDirectory)
            __dbManager__.importList(list_txt)
            cli_log.info("Updated %s items.", str(len(list_txt)))

        if interface.config.overwrite:
            msg = 'Overwrite enabled.'
            pixivutil2.PixivHelper.print_and_log('info', msg)

        if interface.config.dayLastUpdated != 0 and interface.config.processFromDb:
            pixivutil2.PixivHelper.print_and_log('info',
                                    'Only process members where the last update is >= ' + str(interface.config.dayLastUpdated) + ' days ago')

        if interface.config.dateDiff > 0:
            pixivutil2.PixivHelper.print_and_log('info', 'Only process image where day last updated >= ' + str(interface.config.dateDiff))

        if interface.config.useBlacklistTags:
            interface.blacklist_tags = PixivTags.parseTagsList("blacklist_tags.txt")
            pixivutil2.PixivHelper.print_and_log('info', 'Using Blacklist Tags: %s items.', len(interface.blacklist_tags))

        if interface.config.useBlacklistMembers:

            interface.blacklist_members = PixivTags.parseTagsList("blacklist_members.txt")
            pixivutil2.PixivHelper.print_and_log('info', 'Using Blacklist Members: %s members.', len(interface.blacklist_members))

        if interface.config.useSuppressTags:
            interface.suppress_tags = PixivTags.parseTagsList("suppress_tags.txt")
            pixivutil2.PixivHelper.print_and_log('info', 'Using Suppress Tags: %s items.', len(interface.suppress_tags))

        if interface.config.createWebm:
            import shlex
            cmd = "{0} -encoders".format(interface.config.ffmpeg)
            ffmpeg_args = shlex.split(cmd)
            try:
                p = subprocess.Popen(ffmpeg_args, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
                buff = p.stdout.read()
                if buff.find(interface.config.ffmpegCodec) == 0:
                    interface.config.createWebm = False
                    pixivutil2.PixivHelper.print_and_log('error', '{0}'.format("#" * 80))
                    pixivutil2.PixivHelper.print_and_log('error', 'Missing {0} encoder, createWebm disabled.'.format(interface.config.ffmpegCodec))
                    pixivutil2.PixivHelper.print_and_log('error', 'Command used: {0}.'.format(cmd))
                    pixivutil2.PixivHelper.print_and_log('info', 'Please download ffmpeg with {0} encoder enabled.'.format(interface.config.ffmpegCodec))
                    pixivutil2.PixivHelper.print_and_log('error', '{0}'.format("#" * 80))
            except Exception as ex:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                interface.config.createWebm = False
                pixivutil2.PixivHelper.print_and_log('error', '{0}'.format("#" * 80))
                pixivutil2.PixivHelper.print_and_log('error', 'Failed to load ffmpeg, createWebm disabled: {0}'.format(exc_value))
                pixivutil2.PixivHelper.print_and_log('error', 'Command used: {0}.'.format(cmd))
                pixivutil2.PixivHelper.print_and_log('info', 'Please download ffmpeg with {0} encoder enabled.'.format(interface.config.ffmpegCodec))
                pixivutil2.PixivHelper.print_and_log('error', '{0}'.format("#" * 80))

        if interface.config.useLocalTimezone:
            pixivutil2.PixivHelper.print_and_log("info", "Using local timezone: %s", pixivutil2.PixivHelper.LocalUTCOffsetTimezone())

        interface.probe()

        username = interface.config.username
        if username == '':
            username = input('Username ? ')
        else:
            msg = 'Using Username: ' + username
            cli_log.info(msg)
            cli_log.info(msg)

        password = interface.config.password
        if password == '':
            if os.name == 'nt':
                win_unicode_console.disable()
            password = getpass.getpass('Password ? ')
            if os.name == 'nt':
                win_unicode_console.enable()

        if np_is_valid and np != 0:  # Yavos: overwrite config-data
            msg = 'Limit up to: ' + str(np) + ' page(s). (set via commandline)'
            cli_log.info(msg)
            cli_log.info(msg)
        elif interface.config.numberOfPage != 0:
            msg = 'Limit up to: ' + str(interface.config.numberOfPage) + ' page(s).'
            cli_log.info(msg)
            cli_log.info(msg)

        result = interface.doLogin(password, username)

        if result:
            np_is_valid, op_is_valid, selection = interface.main_loop(ewd, op_is_valid, selection, np_is_valid, args)

            if start_iv:  # Yavos: adding start_irfan_view-handling
                pixivutil2.PixivHelper.startIrfanView(dfilename, interface.config.IrfanViewPath, start_irfan_slide, start_irfan_view)
        else:
            interface.last_error_code = PixivException.NOT_LOGGED_IN
    except PixivException as pex:
        pixivutil2.PixivHelper.print_and_log('error', pex.message)
        interface.last_error_code = pex.errorCode
    except Exception as ex:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        cli_log.exception('Unknown Error: %s', str(exc_value))
        interface.last_error_code = getattr(ex, 'errorCode', -1)
    finally:
        __dbManager__.close()
        if not ewd:  # Yavos: prevent input on exitwhendone
            if selection is None or selection != 'x':
                input('press enter to exit.')
        cli_log.setLevel("INFO")
        cli_log.info('EXIT: %s', interface.last_error_code)
        cli_log.info('###############################################################')
        sys.exit(interface.last_error_code)


if __name__ == '__main__':
    main()
