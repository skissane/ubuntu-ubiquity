#! /usr/bin/python
# -*- coding: UTF-8 -*-

# Copyright (C) 2005, 2006 Canonical Ltd.
# Written by Colin Watson <cjwatson@ubuntu.com>.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import sys
import os
import types
import signal
import subprocess
import re
import syslog

import debconf
from ubiquity.debconfcommunicator import DebconfCommunicator

from ubiquity.debconffilter import DebconfFilter

# We identify as this to debconf.
PACKAGE = 'ubiquity'

# Bitfield constants for process_input and process_output.
DEBCONF_IO_IN = 1
DEBCONF_IO_OUT = 2
DEBCONF_IO_ERR = 4
DEBCONF_IO_HUP = 8

class FilteredCommand(object):
    def __init__(self, frontend, db=None):
        self.frontend = frontend
        # db does not normally need to be specified.
        self.db = db
        self.done = False
        self.current_question = None
        self.succeeded = False

    @classmethod
    def debug_enabled(self):
        return ('UBIQUITY_DEBUG_CORE' in os.environ and
                os.environ['UBIQUITY_DEBUG_CORE'] == '1')

    @classmethod
    def debug(self, fmt, *args):
        if self.debug_enabled():
            import time
            # bizarre time formatting code per syslogd
            time_str = time.ctime()[4:19]
            message = fmt % args
            print >>sys.stderr, '%s %s: %s' % (time_str, PACKAGE, message)

    def start(self, auto_process=False):
        self.status = None
        self.db = DebconfCommunicator(PACKAGE, cloexec=True)
        prep = self.prepare()
        self.command = ['log-output', '-t', 'ubiquity', '--pass-stdout']
        if isinstance(prep[0], types.StringTypes):
            self.command.append(prep[0])
        else:
            self.command.extend(prep[0])
        question_patterns = prep[1]
        if len(prep) > 2:
            env = prep[2]
        else:
            env = {}

        self.ui_loop_level = 0

        self.debug("Starting up '%s' for %s.%s", self.command,
                   self.__class__.__module__, self.__class__.__name__)
        self.debug("Watching for question patterns %s",
                   ', '.join(question_patterns))

        widgets = {}
        for pattern in question_patterns:
            widgets[pattern] = self
        self.dbfilter = DebconfFilter(self.db, widgets)

        # TODO: Set as unseen all questions that we're going to ask.

        if auto_process:
            self.dbfilter.start(self.command, blocking=False, extra_env=env)
            # Clearly, this isn't enough for full non-blocking operation.
            # However, debconf itself is generally quick, and the confmodule
            # will generally be listening for a reply when we try to send
            # one; the slow bit is waiting for the confmodule to decide to
            # send a command. Therefore, this is the only file descriptor we
            # bother to watch, which greatly simplifies our life.
            self.frontend.watch_debconf_fd(
                self.dbfilter.subout_fd, self.process_input)
        else:
            self.dbfilter.start(self.command, blocking=True, extra_env=env)

    def process_line(self):
        return self.dbfilter.process_line()

    def wait(self):
        ret = self.dbfilter.wait()

        # TODO: error message if ret != 0 and ret != 10
        self.debug("%s exited with code %d", self.command, ret)

        self.cleanup()

        self.db.shutdown()

        return ret

    def cleanup(self):
        pass

    def run_command(self, auto_process=False):
        # TODO cjwatson 2006-02-25: Hack to allow _apply functions to be run
        # from within the debconffiltered Config class.
        if self.frontend is None:
            prep = self.prepare()
            self.command = ['log-output', '-t', 'ubiquity', '--pass-stdout']
            if isinstance(prep[0], types.StringTypes):
                self.command.append(prep[0])
            else:
                self.command.extend(prep[0])
            self.debug("Starting up '%s' for %s.%s", self.command,
                       self.__class__.__module__, self.__class__.__name__)
            if len(prep) > 2:
                env = prep[2]
            else:
                env = {}

            def subprocess_setup():
                for key, value in env.iteritems():
                    os.environ[key] = value
                os.environ['LC_COLLATE'] = 'C'
                # Python installs a SIGPIPE handler by default. This is bad
                # for non-Python subprocesses, which need SIGPIPE set to the
                # default action or else they won't notice if the
                # debconffilter dies.
                signal.signal(signal.SIGPIPE, signal.SIG_DFL)

            ret = subprocess.call(self.command, preexec_fn=subprocess_setup)
            if ret != 0:
                self.debug("%s exited with code %d", self.command, ret)
            return ret

        self.start(auto_process=auto_process)
        if auto_process:
            self.enter_ui_loop()
            if self.status is None:
                self.status = self.wait()
        else:
            while self.process_line():
                pass
            self.status = self.wait()
        return self.status

    def process_input(self, source, condition):
        if source != self.dbfilter.subout_fd:
            return True

        call_again = True

        if condition & DEBCONF_IO_IN:
            if not self.process_line():
                call_again = False

        if (condition & DEBCONF_IO_ERR) or (condition & DEBCONF_IO_HUP):
            call_again = False

        if not call_again:
            # TODO cjwatson 2006-02-08: We hope this happens quickly! It
            # would be better to do this out-of-band somehow.
            self.status = self.wait()
            self.exit_ui_loops()
            self.frontend.debconffilter_done(self)

        return call_again

    def question_type(self, question):
        try:
            return self.db.metaget(question, 'Type')
        except debconf.DebconfError:
            return ''

    # Split a string on commas, stripping surrounding whitespace, and
    # honouring backslash-quoting.
    def split_choices(self, text):
        textlen = len(text)
        index = 0
        items = []
        item = ''

        while index < textlen:
            if text[index] == '\\' and index + 1 < textlen:
                if text[index + 1] == ',' or text[index + 1] == ' ':
                    item += text[index + 1]
                    index += 1
            elif text[index] == ',':
                items.append(item.strip())
                item = ''
            else:
                item += text[index]
            index += 1

        if item != '':
            items.append(item.strip())

        return items

    def choices_untranslated(self, question):
        choices = unicode(self.db.metaget(question, 'choices-c'),
                          'utf-8', 'replace')
        return self.split_choices(choices)

    def choices(self, question):
        choices = unicode(self.db.metaget(question, 'choices'),
                          'utf-8', 'replace')
        return self.split_choices(choices)

    def choices_display_map(self, question):
        """Returns a mapping from displayed (translated) choices to
        database (untranslated) choices.  It can be used both ways,
        since both choices and the untranslated choices are sequences
        without duplication.
        """

        _map = {}
        choices = self.choices(question)
        choices_c = self.choices_untranslated(question)
        for i in range(len(choices)):
            _map[choices[i]] = choices_c[i]
        return _map

    def description(self, question):
        return unicode(self.db.metaget(question, 'description'),
                       'utf-8', 'replace')

    def extended_description(self, question):
        old_capb = self.db.capb()
        capb_list = old_capb.split()
        capb_list.append('escape')
        self.db.capb(' '.join(capb_list))
        data = unicode(self.db.metaget(question, 'extended_description'),
                       'utf-8', 'replace')
        self.db.capb(old_capb)
        return data

    def translate_to_c(self, question, value):
        choices = self.choices(question)
        choices_c = self.choices_untranslated(question)
        for i in range(len(choices)):
            if choices[i] == value:
                return choices_c[i]
        raise ValueError, value

    def value_index(self, question):
        value = self.db.get(question)
        choices_c = self.choices_untranslated(question)
        for i in range(len(choices_c)):
            if choices_c[i] == value:
                return i
        raise ValueError, value

    def escape(self, text):
        escaped = text.replace('\\', '\\\\').replace('\n', '\\n')
        return re.sub(r'(\s)', r'\\\1', escaped)

    def preseed(self, name, value, seen=True, escape=False):
        if escape:
            value = self.escape(value)
        value = value.encode("UTF-8", "ignore")
        if escape:
            old_capb = self.db.capb()
            capb_list = old_capb.split()
            capb_list.append('escape')
            self.db.capb(' '.join(capb_list))
        try:
            self.db.set(name, value)
        except debconf.DebconfError:
            self.db.register('debian-installer/dummy', name)
            self.db.set(name, value)
            self.db.subst(name, 'ID', name)
        if escape:
            self.db.capb(old_capb)

        if seen:
            self.db.fset(name, 'seen', 'true')

    def preseed_bool(self, name, value, seen=True):
        if value:
            self.preseed(name, 'true', seen, False)
        else:
            self.preseed(name, 'false', seen, False)


    def preseed_as_c(self, name, value, seen=True):
        self.preseed(name, self.translate_to_c(name, value), seen)

    # Cause the frontend to enter a recursive main loop. Will block until
    # something causes the frontend to exit that loop (probably by calling
    # exit_ui_loops).
    def enter_ui_loop(self):
        self.ui_loop_level += 1
        self.frontend.run_main_loop()

    # Exit any recursive main loops we caused the frontend to enter.
    def exit_ui_loops(self):
        while self.ui_loop_level > 0:
            self.ui_loop_level -= 1
            self.frontend.quit_main_loop()

    # User selected OK, Forward, or similar. Subclasses should override this
    # to send user-entered information back to debconf (perhaps using
    # preseed()) and return control to the filtered command. After this
    # point, self.done is set so no further user interaction should take
    # place unless an error resets it.
    def ok_handler(self):
        self.succeeded = True
        self.done = True
        self.exit_ui_loops()

    # User selected Cancel, Back, or similar. Subclasses should override
    # this to send user-entered information back to debconf (perhaps using
    # preseed()) and return control to the filtered command. After this
    # point, self.done is set so no further user interaction should take
    # place unless an error resets it.
    def cancel_handler(self):
        self.succeeded = False
        self.done = True
        self.exit_ui_loops()

    def error(self, priority, question):
        self.succeeded = False
        self.done = False
        return True

    # The confmodule asked a question; process it. Subclasses only need to
    # override this if they want to do something special like updating their
    # UI depending on what questions were asked.

    # TODO: Make the steps references in the individual components, rather than
    # having to define the relationship here?
    def run(self, priority, question):
        if not self.frontend.installing:
            # Make sure any started progress bars are stopped.
            while self.frontend.progress_position.depth() != 0:
                self.frontend.debconf_progress_stop()

        self.current_question = question
        if not self.done:
            self.succeeded = False
            n = self.__class__.__name__
            self.frontend.set_page(n)
            self.enter_ui_loop()
        return self.succeeded

    # Default progress bar handling: just pass it through to the frontend.

    def progress_start(self, progress_min, progress_max, progress_title):
        ret = self.frontend.debconf_progress_start(
            progress_min, progress_max, self.description(progress_title))
        self.frontend.refresh()
        return ret

    def progress_set(self, progress_title, progress_val):
        ret = self.frontend.debconf_progress_set(progress_val)
        self.frontend.refresh()
        return ret

    def progress_step(self, progress_title, progress_inc):
        ret = self.frontend.debconf_progress_step(progress_inc)
        self.frontend.refresh()
        return ret

    def progress_info(self, progress_title, progress_info):
        try:
            ret = self.frontend.debconf_progress_info(
                self.description(progress_info))
            self.frontend.refresh()
            return ret
        except debconf.DebconfError:
            # ignore unknown info templates
            return True

    def progress_stop(self, progress_title):
        ret = self.frontend.debconf_progress_stop()
        self.frontend.refresh()
        return ret

    def progress_region(self, progress_title,
                        progress_region_start, progress_region_end):
        self.frontend.debconf_progress_region(progress_region_start,
                                              progress_region_end)

if __name__ == '__main__':
    fc = FilteredCommand()
    fc.run(sys.argv[1])
