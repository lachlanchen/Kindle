#!/bin/sh
# Fail-closed installer for the audited PW5SE 5.15.1 only.
# This script never uses /mnt/us/emergency.sh and never starts KOReader itself.

set -u

EXPECTED_FIRMWARE="5.15.1"
JOB_NAME="lazying-koreader"
JOB_PATH="/etc/upstart/${JOB_NAME}.conf"
JOB_SHA256="2de0232b971926b7e70d913a27ba76168ed69760504ae2a90947e4402e7e5828"
DEFAULT_CANDIDATE="/tmp/lazying-koreader-autostart.conf"
DISABLE_MARKER="/mnt/us/DISABLE_KOREADER_AUTOSTART"
PARKED_DISABLE_MARKER="/mnt/us/_DISABLE_KOREADER_AUTOSTART"
EMERGENCY_SCRIPT="/mnt/us/emergency.sh"
KOREADER_LAUNCHER="/mnt/us/koreader/koreader.sh"

ROOT_WRITE_ACTIVE=0
RESTORE_ROOT_RO=0
OWNED_JOB_TMP=0
JOB_TMP=""

say() {
    printf '%s\n' "$*"
}

die() {
    say "error=$*" >&2
    exit 1
}

file_sha256() {
    sha256sum "$1" 2>/dev/null | awk '{print $1}'
}

firmware_version() {
    sed -n 's/^Kindle[[:space:]]*\([0-9][0-9.]*\).*$/\1/p' \
        /etc/prettyversion.txt 2>/dev/null | head -n 1
}

job_state() {
    if [ ! -e "${JOB_PATH}" ]; then
        if [ -L "${JOB_PATH}" ]; then
            say "foreign"
        else
            say "absent"
        fi
    elif [ -L "${JOB_PATH}" ] || [ ! -f "${JOB_PATH}" ]; then
        say "foreign"
    elif [ "$(file_sha256 "${JOB_PATH}")" = "${JOB_SHA256}" ]; then
        say "owned"
    else
        say "foreign"
    fi
}

marker_kind() {
    marker_path="$1"
    if [ -L "${marker_path}" ]; then
        say "symlink"
    elif [ -f "${marker_path}" ]; then
        say "file"
    elif [ -d "${marker_path}" ]; then
        say "directory"
    elif [ -e "${marker_path}" ]; then
        say "other"
    else
        say "absent"
    fi
}

marker_switch_state() {
    active_kind="$(marker_kind "${DISABLE_MARKER}")"
    parked_kind="$(marker_kind "${PARKED_DISABLE_MARKER}")"

    case "${active_kind}" in
        symlink|other)
            say "unsafe_active_${active_kind}"
            return 0
            ;;
    esac
    case "${parked_kind}" in
        symlink|other)
            say "unsafe_parked_${parked_kind}"
            return 0
            ;;
    esac

    if [ "${active_kind}" != "absent" ] && [ "${parked_kind}" != "absent" ]; then
        say "ambiguous_both_present"
    elif [ "${active_kind}" = "file" ] || [ "${active_kind}" = "directory" ]; then
        say "disabled_${active_kind}"
    elif [ "${parked_kind}" = "file" ] || [ "${parked_kind}" = "directory" ]; then
        say "enabled_${parked_kind}"
    else
        say "missing_both"
    fi
}

root_is_rw() {
    awk '
        $2 == "/" {
            found = 1
            count = split($4, option, ",")
            for (i = 1; i <= count; i++) {
                if (option[i] == "rw") exit 0
            }
            exit 1
        }
        END { if (!found) exit 1 }
    ' /proc/mounts
}

cleanup() {
    rc=$?
    trap - 0 1 2 15
    if [ "${ROOT_WRITE_ACTIVE}" -eq 1 ]; then
        if [ "${OWNED_JOB_TMP}" -eq 1 ] && [ -n "${JOB_TMP}" ]; then
            rm -f "${JOB_TMP}" || rc=1
        fi
        sync
        if [ "${RESTORE_ROOT_RO}" -eq 1 ]; then
            mntroot ro >/dev/null 2>&1 || rc=1
        fi
    fi
    exit "${rc}"
}

trap cleanup 0
trap 'exit 130' 1 2 15

begin_root_write() {
    ROOT_WRITE_ACTIVE=1
    if root_is_rw; then
        RESTORE_ROOT_RO=0
    else
        RESTORE_ROOT_RO=1
        mntroot rw >/dev/null 2>&1 || die "could_not_remount_root_rw"
    fi
}

finish_root_write() {
    sync
    if [ "${RESTORE_ROOT_RO}" -eq 1 ]; then
        mntroot ro >/dev/null 2>&1 || die "could_not_restore_root_ro"
    fi
    ROOT_WRITE_ACTIVE=0
    RESTORE_ROOT_RO=0
    OWNED_JOB_TMP=0
    JOB_TMP=""
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "missing_command_$1"
}

reload_upstart() {
    attempt=1
    while [ "${attempt}" -le 5 ]; do
        if initctl reload-configuration >/dev/null 2>&1; then
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 1
    done
    return 1
}

reload_and_require_registered_job() {
    reload_upstart || return 1
    attempt=1
    while [ "${attempt}" -le 5 ]; do
        if initctl status "${JOB_NAME}" >/dev/null 2>&1; then
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 1
    done
    return 1
}

assert_owned_or_absent_job() {
    state="$(job_state)"
    [ "${state}" != "foreign" ] || die "foreign_upstart_job_refused"
}

assert_owned_job() {
    [ "$(job_state)" = "owned" ] || die "owned_upstart_job_required"
}

assert_audited_runtime() {
    firmware="$(firmware_version)"
    [ "${firmware}" = "${EXPECTED_FIRMWARE}" ] || \
        die "firmware_mismatch_expected_${EXPECTED_FIRMWARE}"

    [ -d /etc/upstart ] || die "missing_etc_upstart"
    [ -f /etc/upstart/kmc.conf ] || die "missing_kmc_job"
    [ -f /etc/upstart/home_wait.conf ] || die "missing_home_wait_job"
    [ -f /etc/upstart/lab126_gui.conf ] || die "missing_lab126_gui_job"
    [ -f /etc/upstart/kppmainapp.conf ] || die "missing_kppmainapp_job"
    grep -Fq 'start on framework_ready' /etc/upstart/kmc.conf || \
        die "unexpected_framework_ready_boundary"
    grep -Fq 'lipc-wait-event' /etc/upstart/home_wait.conf || \
        die "unexpected_home_wait_boundary"
    grep -Fq 'appStarted' /etc/upstart/home_wait.conf || \
        die "unexpected_home_wait_event"

    require_command awk
    require_command chmod
    require_command chown
    require_command cp
    require_command grep
    require_command head
    require_command initctl
    require_command lipc-wait-event
    require_command mntroot
    require_command mv
    require_command pidof
    require_command rm
    require_command rmdir
    require_command sed
    require_command sha256sum
    require_command sleep
    require_command sync

    # Kindle 5.15.1 ships Upstart 0.6.6, whose initctl has no show-config
    # command. A known stock job status is the live daemon capability check.
    initctl status kmc >/dev/null 2>&1 || \
        die "upstart_stock_job_status_unavailable"
    { [ ! -e "${EMERGENCY_SCRIPT}" ] && [ ! -L "${EMERGENCY_SCRIPT}" ]; } || \
        die "root_emergency_script_present"
    { [ -f "${KOREADER_LAUNCHER}" ] && [ ! -L "${KOREADER_LAUNCHER}" ]; } || \
        die "koreader_launcher_missing_or_symlink"
    assert_owned_or_absent_job
}

ensure_disabled() {
    switch_state="$(marker_switch_state)"
    case "${switch_state}" in
        disabled_file|disabled_directory)
            return 0
            ;;
        enabled_file|enabled_directory)
            rename_marker_exact \
                "${PARKED_DISABLE_MARKER}" \
                "${DISABLE_MARKER}" \
                "disabled_${switch_state#enabled_}"
            ;;
        missing_both)
            umask 022
            : >"${DISABLE_MARKER}" || die "could_not_create_initial_disable_marker"
            sync
            [ "$(marker_switch_state)" = "disabled_file" ] || \
                die "initial_disable_marker_not_durable"
            ;;
        ambiguous_both_present)
            die "ambiguous_both_markers_refused"
            ;;
        unsafe_*)
            die "unsafe_marker_type_refused_${switch_state}"
            ;;
        *)
            die "unknown_marker_switch_state"
            ;;
    esac
}

rename_marker_exact() {
    marker_from="$1"
    marker_to="$2"
    expected_switch_state="$3"
    marker_from_kind="$(marker_kind "${marker_from}")"
    marker_to_kind="$(marker_kind "${marker_to}")"

    case "${marker_from_kind}" in
        file|directory) ;;
        symlink) die "source_marker_symlink_refused" ;;
        *) die "source_marker_not_renameable" ;;
    esac
    [ "${marker_to_kind}" = "absent" ] || die "destination_marker_already_exists"

    # Both names are in /mnt/us, so this is one same-filesystem rename. The
    # marker and any contents are preserved; enable/disable never deletes it.
    mv "${marker_from}" "${marker_to}" || die "marker_atomic_rename_failed"
    sync
    [ "$(marker_kind "${marker_from}")" = "absent" ] || \
        die "source_marker_remained_after_rename"
    [ "$(marker_kind "${marker_to}")" = "${marker_from_kind}" ] || \
        die "destination_marker_type_changed"
    [ "$(marker_switch_state)" = "${expected_switch_state}" ] || \
        die "marker_switch_state_mismatch_after_rename"
}

ensure_enabled() {
    switch_state="$(marker_switch_state)"
    case "${switch_state}" in
        enabled_file|enabled_directory)
            return 0
            ;;
        disabled_file|disabled_directory)
            rename_marker_exact \
                "${DISABLE_MARKER}" \
                "${PARKED_DISABLE_MARKER}" \
                "enabled_${switch_state#disabled_}"
            ;;
        missing_both)
            die "marker_switch_missing_refusing_enable"
            ;;
        ambiguous_both_present)
            die "ambiguous_both_markers_refused"
            ;;
        unsafe_*)
            die "unsafe_marker_type_refused_${switch_state}"
            ;;
        *)
            die "unknown_marker_switch_state"
            ;;
    esac
}

print_status() {
    firmware="$(firmware_version)"
    state="$(job_state)"
    active_marker="$(marker_kind "${DISABLE_MARKER}")"
    parked_marker="$(marker_kind "${PARKED_DISABLE_MARKER}")"
    switch_state="$(marker_switch_state)"

    say "firmware=${firmware:-unknown}"
    say "job=${state}"
    say "disable_marker=${active_marker}"
    say "parked_disable_marker=${parked_marker}"
    say "marker_switch=${switch_state}"
    if [ -e "${EMERGENCY_SCRIPT}" ] || [ -L "${EMERGENCY_SCRIPT}" ]; then
        say "emergency_script=present"
    else
        say "emergency_script=absent"
    fi
    if [ -f "${KOREADER_LAUNCHER}" ] && [ ! -L "${KOREADER_LAUNCHER}" ]; then
        say "koreader_launcher=present"
    else
        say "koreader_launcher=absent"
    fi

    if [ "${state}" = "owned" ] && \
        { [ "${switch_state}" = "enabled_file" ] || [ "${switch_state}" = "enabled_directory" ]; } && \
        [ ! -e "${EMERGENCY_SCRIPT}" ] && [ ! -L "${EMERGENCY_SCRIPT}" ] && \
        [ -f "${KOREADER_LAUNCHER}" ] && [ ! -L "${KOREADER_LAUNCHER}" ]; then
        say "autostart=enabled_next_boot"
    elif [ "${state}" = "owned" ] && [ "${active_marker}" = "absent" ] && \
        [ ! -e "${EMERGENCY_SCRIPT}" ] && [ ! -L "${EMERGENCY_SCRIPT}" ] && \
        [ -f "${KOREADER_LAUNCHER}" ] && [ ! -L "${KOREADER_LAUNCHER}" ]; then
        # The installed job checks only the active marker. Make an invalid
        # active-absent state explicit instead of misreporting it as disabled.
        say "autostart=unsafe_active_marker_absent"
    else
        say "autostart=disabled_or_unavailable"
    fi
}

install_job() {
    candidate="${1:-${DEFAULT_CANDIDATE}}"
    assert_audited_runtime
    { [ -f "${candidate}" ] && [ ! -L "${candidate}" ]; } || \
        die "candidate_job_missing_or_symlink"
    [ "$(file_sha256 "${candidate}")" = "${JOB_SHA256}" ] || \
        die "candidate_job_hash_mismatch"

    # Stage every install disabled. Enabling is a separate explicit action.
    ensure_disabled
    if [ "$(job_state)" = "owned" ]; then
        reload_and_require_registered_job || \
            die "upstart_reload_or_registration_failed"
        say "result=already_installed_disabled"
        print_status
        return 0
    fi

    begin_root_write
    JOB_TMP="${JOB_PATH}.lazying-art.$$"
    { [ ! -e "${JOB_TMP}" ] && [ ! -L "${JOB_TMP}" ]; } || \
        die "owned_job_temp_path_exists"
    # Claim this previously absent exact path before cp so a partial copy is
    # removed by the root-restoration trap.
    OWNED_JOB_TMP=1
    cp "${candidate}" "${JOB_TMP}" || die "job_copy_failed"
    [ "$(file_sha256 "${JOB_TMP}")" = "${JOB_SHA256}" ] || \
        die "job_temp_hash_mismatch"
    chown root:root "${JOB_TMP}" || die "job_chown_failed"
    chmod 0644 "${JOB_TMP}" || die "job_chmod_failed"
    { [ ! -e "${JOB_PATH}" ] && [ ! -L "${JOB_PATH}" ]; } || \
        die "job_path_appeared_during_install"
    mv "${JOB_TMP}" "${JOB_PATH}" || die "job_atomic_publish_failed"
    OWNED_JOB_TMP=0
    JOB_TMP=""
    [ "$(job_state)" = "owned" ] || die "published_job_hash_mismatch"
    finish_root_write

    # Reloading configuration does not start a job; the disable marker remains.
    reload_and_require_registered_job || \
        die "upstart_reload_or_registration_failed_job_remains_disabled"
    say "result=installed_disabled"
    print_status
}

enable_job() {
    assert_audited_runtime
    assert_owned_job
    initctl status "${JOB_NAME}" >/dev/null 2>&1 || \
        die "installed_job_not_registered"
    ensure_enabled
    say "result=enabled_for_next_boot"
    print_status
}

disable_job() {
    ensure_disabled
    say "result=disabled_for_next_boot"
    print_status
}

uninstall_job() {
    # Native UI is the recovery default even if later checks refuse removal.
    ensure_disabled
    state="$(job_state)"
    [ "${state}" != "foreign" ] || die "foreign_upstart_job_refused"
    if [ "${state}" = "absent" ]; then
        say "result=already_uninstalled_disabled"
        print_status
        return 0
    fi

    begin_root_write
    [ "$(job_state)" = "owned" ] || die "job_changed_before_uninstall"
    rm -f "${JOB_PATH}" || die "job_remove_failed"
    [ ! -e "${JOB_PATH}" ] || die "job_still_present"
    finish_root_write
    reload_upstart || \
        die "upstart_reload_failed_job_is_removed"
    say "result=uninstalled_disabled"
    print_status
}

usage() {
    say "usage: $0 audit|status|install|enable|disable|uninstall [candidate-conf]"
}

action="${1:-status}"
case "${action}" in
    audit)
        assert_audited_runtime
        say "result=audit_passed"
        print_status
        ;;
    status)
        print_status
        ;;
    install)
        install_job "${2:-${DEFAULT_CANDIDATE}}"
        ;;
    enable)
        enable_job
        ;;
    disable)
        disable_job
        ;;
    uninstall)
        uninstall_job
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
