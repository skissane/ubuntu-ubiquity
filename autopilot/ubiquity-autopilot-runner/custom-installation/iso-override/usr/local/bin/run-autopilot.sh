#!/bin/sh

#
# This script runs autopilot
#

# Copyright © 2013 Canonical Ltd.
# Author: Jean-baptiste Lallement <jean-baptiste.lallement@canonical.com>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 2, as published by the
# Free Software Foundation.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
set -eu

TESTBASE=/var/local/autopilot/
AP_ARTIFACTS=$TESTBASE/videos/
AP_RESULTS=$TESTBASE/junit/
AP_LOGS=$TESTBASE/logs/
AP_TESTSUITES=$TESTBASE/testsuites
AP_LOGFILE=$AP_LOGS/autopilot.log
AP_SUMMARY=$AP_LOGS/summary.log
SPOOLDIR=$TESTBASE/spool
AP_OPTS="-v -f xml"
RMD_OPTS="-r -rd $AP_ARTIFACTS --record-options=--fps=6,--no-wm-check"
# TESTING ONLY -- Recording is disabled
AP_OPTS="-f xml"
TSBRANCH=lp:~dpniel/ubiquity/autopilot
TSEXPORT=$HOME/ubiquity-autopilot
SESSION_LOG=""
ARTIFACTS="$TESTBASE /var/log/installer /var/log/syslog $HOME/.cache/upstart /var/crash"
SHUTDOWN=1
TIMEOUT=1200  # 20min timeout

# Specific configurations for various DE
case $SESSION in
    ubuntu)    # Covers Ubuntu and Edubuntu
        SESSION_LOG=$HOME/.cache/upstart/gnome-session.log
        ;;
    xubuntu)
        SESSION_LOG=$HOME/.cache/upstart/startxfce4.log
        ;;
    Lubuntu)
        SESSION_LOG=$HOME/.cache/lxsession/Lubuntu/run.log
        ARTIFACTS="$ARTIFACTS $HOME/.cache/lxsession"
        ;;
    gnome)     # ubuntu-gnome
        SESSION_LOG=$HOME/.cache/upstart/gnome-session.log
esac

PACKAGES="bzr ssh python3-autopilot libautopilot-gtk python3-xlib \
    recordmydesktop"

export DEBIAN_FRONTEND=noninteractive

# Define general configuration files 
[ -f $TESTBASE/config ] && . $TESTBASE/config

on_exit() {
    # Exit handler
    echo "I: Archiving artifacts"
    archive=/tmp/artifacts
    for artifact in $ARTIFACTS; do
        [ -e "$artifact" ] && sudo tar rf ${archive}.tar $artifact || true
    done

    # Find a better way. ttys are a bit limited and sometimes output is
    # truncated or messages are skipped by the kernel if it goes too fast.
    if [ -f ${archive}.tar ]; then
        sudo stty -F /dev/ttyS1 raw speed 115200
        gzip -9 -c ${archive}.tar > ${archive}.tgz
        sudo sh -c "cat ${archive}.tgz>/dev/ttyS1"
    fi

    shutdown_host
}
trap on_exit EXIT INT QUIT ABRT PIPE TERM

usage() {
    # Display usage and exit
    cat<<EOF
Usage: $(basename $0) [OPTIONS...]
Run autopilot tests in $SPOOLDIR

Options:
  -h, --help      This help
  -d, --debug     Enable debug mode
  -N, --new       Restart all the tests in $AP_TESTSUITES otherwise
                  only the remaining tests in $SPOOLDIR are run
  -R, --norecord  Do not use recordmydesktop.
  -S, --noshutdown
                  Do not shutdown the system after the tests

EOF
    exit 1
}

setup_tests() {
    # Prepares the environment for the tests
    flag=$HOME/.ap_setup_done

    [ -e "$flag" ] && return 0

    xterm &  # Easier to debug from a live session, and rarely broken
    sudo stty -F /dev/ttyS0 raw speed 115200
    
    tail_logs $SESSION_LOG /var/log/syslog
    # Disable notifications and screensaver
    if which gsettings >/dev/null 2>&1; then 
        echo "I: Disabling crash notifications"
        gsettings set com.ubuntu.update-notifier show-apport-crashes false
        echo "I: Disabling screensaver"
        gsettings set org.gnome.desktop.screensaver idle-activation-enabled false
    fi

    # Loads the list of test and queue them in test spool
    sudo mkdir -p $SPOOLDIR $AP_ARTIFACTS $AP_RESULTS $AP_LOGS
    sudo chown -R $USER:$USER $TESTBASE $SPOOLDIR $AP_ARTIFACTS $AP_RESULTS $AP_LOGS

    echo "I: Installating additional packages"
    sudo apt-get update
    rc=0
    sudo apt-get install -yq $PACKAGES || rc=$?
    if [ $rc -gt 0 ]; then
        echo "E: Required packages failed to install. Aborting!"
        exit 1
    fi

    echo "I: Branch $TSBRANCH"
    bzr export $TSEXPORT $TSBRANCH

    if [ -e "$AP_TESTSUITES" ]; then
        (cd $SPOOLDIR; touch $(cat $AP_TESTSUITES))
    fi

    touch $flag
}

shutdown_host() {
    # Shutdown host
    sleep 10
    if [ $SHUTDOWN -eq 1 ]; then
        echo "I: Shutting down test environment"
        sudo shutdown -h now
    else
        echo "I: Shutdown disabled, host will keep running"
    fi
}

tail_logs() {
    # Tail log files in -F mode in background
    #   
    # $@ List of log files
    for log in $@; do
        if [ -f "$log" ]; then
            sudo sh -c "/bin/busybox tail -n0 -f $log | mawk -Winteractive -v logfile=\"$log\" '{print logfile\":\",\$0}' > /dev/ttyS0" &
        fi
    done
    }


run_tests() {
    # Runs all the tests in spooldir
    #
    # $1: Spool directory
    spooldir=$1
    if [ ! -d $spooldir ]; then
        echo "E: '$spooldir is not a directory. Exiting!"
        exit 1
    fi

    if ! which autopilot-py3 >/dev/null 2>&1; then
        echo "E: autopilot is required to run autopilot tests"
        echo "autopilot_installed (see autopilot.log for details): ERROR" >> $AP_SUMMARY
        shutdown_host
        exit 1
    fi
    echo "autopilot_installed: PASS" >> $AP_SUMMARY

    exec >>$AP_LOGFILE
    exec 2>&1
    touch $AP_LOGFILE
    tail_logs $AP_LOGFILE

    echo "I: Launching Ubiquity"
    cd $TSEXPORT/autopilot
    ./run_ubiquity &
    sleep 30
    tail_logs /var/log/installer/debug
    for testfile in $(ls -d $spooldir/* 2>/dev/null); do
        testname=$(basename $testfile)
        # We don't want to fail if AP fail but we want the return code
        set +e  
        echo "I: Running autopilot run $testname $AP_OPTS -o $AP_RESULTS/$testname.xml"
        timeout -s 9 -k 30 $TIMEOUT ./autopilot run $testname $AP_OPTS -o $AP_RESULTS/${testname}.xml
        AP_RC=$?
        if [ $AP_RC -gt 0 ]; then
            echo "${testname}: FAIL" >> $AP_SUMMARY
        else
            echo "${testname}: DONE" >> $AP_SUMMARY
        fi
        set -e
        sudo rm -f $testfile
    done
}

reset_test() {
    # Reset the tests for a new run
    rm -f $HOME/.ap_setup_done $AP_SUMMARY $AP_LOGFILE $SPOOLDIR/* $AP_ARTIFACTS/* $AP_RESULTS/*
}
SHORTOPTS="hdNRS"
LONGOPTS="help,debug,new,norecord,noshutdown"

TEMP=$(getopt -o $SHORTOPTS --long $LONGOPTS -- "$@")
eval set -- "$TEMP"

while true ; do
    case "$1" in
    -h|--help)
        usage;;
    -d|--debug)
        set -x
        shift;;
    -N|--new)
        reset_test
        shift;;
    -R|--norecord)
        RMD_OPTS=""
        shift;;
    -S|--noshutdown)
        SHUTDOWN=0
        shift;;
    --) shift;
        break;;
    *) usage;;
    esac
done

setup_tests
if [ -f "/usr/lib/libeatmydata/libeatmydata.so" ]; then
    echo "I: Enabling eatmydata"
    export LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD:}/usr/lib/libeatmydata/libeatmydata.so"
fi
# Specific option for recordmydesktop for unity tests
# It is suspected to caused memory fragmentation and make the test crash
if [ -e "$AP_TESTSUITES" ]; then
    if grep -qw "unity" "$AP_TESTSUITES" 2>/dev/null; then
        RMD_OPTS="$RMD_OPTS --record-options=--fps=6,--no-wm-check"
    fi
fi

if which recordmydesktop >/dev/null 2>&1; then
    AP_OPTS="$AP_OPTS $RMD_OPTS"
fi

run_tests $SPOOLDIR
exit 0
